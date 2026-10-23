import asyncio
import logging
from uuid import UUID, uuid4

from rag.concurrency import complete_before_cancel, native_call
from rag.config import PublicSettings, Settings
from rag.db import Database
from rag.embedding import Embedder
from rag.extraction import ExtractionError, extract_pages
from rag.llm import Ollama

logger = logging.getLogger(__name__)


class SettingsConflict(ValueError):
    pass


class RuntimeBusy(ValueError):
    pass


class InvalidModel(ValueError):
    pass


class Runtime:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.defaults = settings.public()
        self.revision = 0
        self.updated_at = None
        self.db = Database(settings)
        self.embedder = Embedder(settings)
        self.llm = Ollama(settings)
        # Shared by embeddings and generation: bound CPU concurrency and RAM on WSL.
        self.inference_lock = asyncio.Lock()
        self.task: asyncio.Task | None = None
        self.worker_error = False

    def settings_response(self) -> dict:
        return {
            "revision": self.revision,
            "updated_at": self.updated_at,
            "values": self.settings.public(),
            "defaults": self.defaults,
        }

    def apply_settings(self, settings: Settings, embedder: Embedder | None = None):
        self.settings = settings
        self.db.settings = settings
        self.llm.settings = settings
        if embedder is not None:
            self.embedder = embedder
        self.embedder.settings = settings

    async def update_settings(self, revision: int, values: PublicSettings) -> dict:
        if self.inference_lock.locked():
            raise RuntimeBusy("Há uma resposta ou ingestão em andamento. Tente salvar ao terminar.")
        async with self.inference_lock:
            if revision != self.revision:
                raise SettingsConflict(
                    "As configurações foram alteradas. Recarregue e tente novamente."
                )
            if values.ollama_model != self.settings.ollama_model:
                if not await self.llm.selectable_model(values.ollama_model):
                    raise InvalidModel(
                        "Selecione um modelo de geração instalado localmente, sem serviço de nuvem."
                    )
            updated = self.settings.with_public(values)
            candidate = None
            if updated.cpu_threads != self.settings.cpu_threads:
                candidate = Embedder(updated)
                if self.embedder.model is not None:
                    # Prepare CPU session before committing; a failure leaves both
                    # persisted configuration and the current model untouched.
                    await native_call(candidate.load)

            async def persist_and_apply():
                row = await self.db.save_runtime_settings(revision, values.model_dump())
                if row is None:
                    raise SettingsConflict(
                        "As configurações foram alteradas. Recarregue e tente novamente."
                    )
                self.apply_settings(updated, candidate)
                self.revision, self.updated_at = row["revision"], row["updated_at"]
                return self.settings_response()

            # A browser disconnect or shutdown cannot leave the in-memory snapshot
            # behind a successfully committed database revision.
            return await complete_before_cancel(persist_and_apply())

    async def start(self):
        self.settings.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.settings.models_dir.mkdir(parents=True, exist_ok=True)
        await self.db.open()
        saved = await self.db.load_runtime_settings()
        values = PublicSettings.model_validate({**self.defaults.model_dump(), **saved["values"]})
        self.apply_settings(self.settings.with_public(values))
        self.revision, self.updated_at = saved["revision"], saved["updated_at"]
        documents = await self.db.list_documents()
        known_ids = {str(document["id"]) for document in documents}
        # Interrupted uploads can leave .part or pre-commit files. Only remove files
        # using our own UUID naming scheme, before the server accepts any requests.
        for path in self.settings.uploads_dir.iterdir():
            try:
                UUID(path.name.removesuffix(".part"))
            except ValueError:
                continue
            if path.is_file() and (path.suffix == ".part" or path.name not in known_ids):
                path.unlink(missing_ok=True)
        # Model download happens in the background, so health/UI remain available.
        self.task = asyncio.create_task(self.worker(), name="document-worker")

    async def close(self):
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        await self.llm.close()
        await self.db.close()

    async def worker(self):
        while True:
            try:
                if self.embedder.model is None:
                    async with self.inference_lock:
                        try:
                            self.embedder.status = "loading"
                            await native_call(self.embedder.load)
                        except Exception:
                            self.embedder.model = None
                            self.embedder.status = "error"
                            self.embedder.error = (
                                "Falha no download/carga do embedding; nova tentativa em 60s."
                            )
                            logger.exception("Embedding model initialization failed")
                    if self.embedder.model is None:
                        await asyncio.sleep(60)
                        continue
                document = await self.db.claim()
                self.worker_error = False
                if document is None:
                    await asyncio.sleep(1)
                    continue
                try:
                    async with self.inference_lock:
                        chunks = await native_call(self.ingest, document)
                        await self.db.finish(document["id"], chunks)
                except Exception as exc:
                    logger.exception("Document ingestion failed: %s", document["id"])
                    error = (
                        str(exc)
                        if isinstance(exc, ExtractionError)
                        else (
                            "Falha ao processar o arquivo. "
                            "Verifique a integridade e tente novamente."
                        )
                    )
                    await self.db.fail_document(document["id"], error)
            except asyncio.CancelledError:
                raise
            except Exception:
                self.worker_error = True
                logger.exception("Ingestion worker temporarily unavailable")
                await asyncio.sleep(5)

    def ingest(self, document: dict) -> list[dict]:
        path = self.settings.uploads_dir / str(document["id"])
        pages = extract_pages(
            path,
            document["extension"],
            max_pdf_pages=self.settings.max_pdf_pages,
            max_text_characters=self.settings.max_text_characters,
            max_docx_uncompressed_mb=self.settings.max_docx_uncompressed_mb,
        )
        chunks = self.embedder.documents(pages)
        for ordinal, chunk in enumerate(chunks):
            chunk.update(id=uuid4(), document_id=document["id"], ordinal=ordinal)
        return chunks
