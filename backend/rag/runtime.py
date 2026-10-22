import asyncio
import logging
from uuid import UUID, uuid4

from rag.concurrency import native_call
from rag.config import Settings
from rag.db import Database
from rag.embedding import Embedder
from rag.extraction import ExtractionError, extract_pages
from rag.llm import Ollama

logger = logging.getLogger(__name__)


class Runtime:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.db = Database(settings)
        self.embedder = Embedder(settings)
        self.llm = Ollama(settings)
        # Shared by embeddings and generation: bound CPU concurrency and RAM on WSL.
        self.inference_lock = asyncio.Lock()
        self.task: asyncio.Task | None = None
        self.worker_error = False

    async def start(self):
        self.settings.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.settings.models_dir.mkdir(parents=True, exist_ok=True)
        await self.db.open()
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
        pages = extract_pages(path, document["extension"])
        chunks = self.embedder.documents(pages)
        for ordinal, chunk in enumerate(chunks):
            chunk.update(id=uuid4(), document_id=document["id"], ordinal=ordinal)
        return chunks
