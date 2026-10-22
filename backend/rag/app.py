import asyncio
import hashlib
import json
import logging
import os
import unicodedata
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, StreamingResponse
from psycopg.errors import UniqueViolation
from pydantic import BaseModel, Field, field_validator

from rag.concurrency import native_call
from rag.config import Settings
from rag.llm import build_prompt
from rag.runtime import Runtime

logger = logging.getLogger(__name__)
SUPPORTED = {".pdf", ".txt", ".md", ".docx"}


class HistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    history: list[HistoryMessage] = Field(default_factory=list, max_length=20)
    document_ids: list[UUID] | None = Field(default=None, max_length=200)

    @field_validator("message")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("Escreva uma pergunta.")
        if len(value.encode("utf-8")) > 1500:
            raise ValueError("Pergunta muito longa; limite de 1500 bytes UTF-8.")
        return value.strip()


def event(data: dict) -> str:
    return json.dumps(jsonable_encoder(data), ensure_ascii=False) + "\n"


def safe_filename(name: str | None) -> str:
    name = (name or "documento").replace("\\", "/").split("/")[-1]
    return "".join(char for char in name if not unicodedata.category(char).startswith("C"))[:200]


def create_app(settings: Settings | None = None, runtime=None) -> FastAPI:
    settings = settings or Settings()
    state = runtime or Runtime(settings)

    @asynccontextmanager
    async def lifespan(app):
        try:
            await state.start()
            yield
        finally:
            await state.close()

    app = FastAPI(title="Mini RAG local", version="0.1.0", lifespan=lifespan)
    app.state.runtime = state

    @app.middleware("http")
    async def upload_size_guard(request: Request, call_next):
        # Bound the entire multipart request before Starlette spools it. Route-level
        # streaming alone is too late: multipart parsing happens before the endpoint.
        if request.method == "POST" and request.url.path == "/api/documents":
            limit = settings.max_upload_mb * 1024 * 1024 + 64 * 1024
            content_length = request.headers.get("content-length")
            if content_length:
                try:
                    if int(content_length) > limit:
                        return JSONResponse({"detail": "Arquivo excede o limite de upload."}, 413)
                except ValueError:
                    return JSONResponse({"detail": "Content-Length inválido."}, 400)
            # Starlette reads through Request.stream(); count chunks regardless of header.
            receive = request.receive
            received = 0

            async def limited_receive():
                nonlocal received
                message = await receive()
                received += len(message.get("body", b""))
                if received > limit:
                    raise HTTPException(413, "Arquivo excede o limite de upload.")
                return message

            request._receive = limited_receive
        return await call_next(request)

    @app.get("/api/health")
    async def health():
        try:
            database = await asyncio.wait_for(state.db.health(), timeout=3)
        except Exception:
            database = {"status": "unavailable"}
        model = await state.llm.health()
        return {
            "status": "ok" if database["status"] == "ok" else "degraded",
            "database": database,
            "model": model,
            "embedding": {
                "status": state.embedder.status,
                "name": settings.embedding_model,
                "error": state.embedder.error,
            },
            "worker": {"status": "error" if state.worker_error else "ok"},
            "limits": {
                "max_upload_mb": settings.max_upload_mb,
                "max_documents": settings.max_documents,
            },
            "cpu_threads": settings.cpu_threads,
        }

    @app.get("/api/documents")
    async def documents():
        return {"documents": await state.db.list_documents()}

    @app.post("/api/documents", status_code=201)
    async def upload(file: Annotated[UploadFile, File()]):
        name = safe_filename(file.filename)
        extension = Path(name).suffix.lower()
        if extension not in SUPPORTED:
            raise HTTPException(415, "Use PDF, TXT, Markdown (.md) ou DOCX.")
        document_id = uuid4()
        path = settings.uploads_dir / str(document_id)
        temporary = settings.uploads_dir / f"{document_id}.part"
        size, digest = 0, hashlib.sha256()
        committed = False
        try:
            with temporary.open("xb") as target:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > settings.max_upload_mb * 1024 * 1024:
                        raise HTTPException(
                            413, f"Limite de {settings.max_upload_mb} MB por arquivo."
                        )
                    digest.update(chunk)
                    await native_call(target.write, chunk)
            if size == 0:
                raise HTTPException(422, "O arquivo está vazio.")
            os.replace(temporary, path)
            document = await state.db.add_document(
                {
                    "id": document_id,
                    "name": name,
                    "extension": extension,
                    "sha256": digest.hexdigest(),
                    "size_bytes": size,
                }
            )
            committed = True
            return document
        except UniqueViolation as exc:
            raise HTTPException(
                409, "Este arquivo já está na biblioteca (conteúdo idêntico)."
            ) from exc
        except OverflowError as exc:
            raise HTTPException(409, str(exc)) from exc
        finally:
            await file.close()
            temporary.unlink(missing_ok=True)
            if not committed:
                path.unlink(missing_ok=True)

    @app.delete("/api/documents/{document_id}", status_code=204)
    async def delete(document_id: UUID):
        if not await state.db.delete_document(document_id):
            raise HTTPException(404, "Documento não encontrado.")
        (settings.uploads_dir / str(document_id)).unlink(missing_ok=True)
        return Response(status_code=204)

    @app.post("/api/documents/{document_id}/retry")
    async def retry(document_id: UUID):
        document = await state.db.retry_document(document_id)
        if document is None:
            raise HTTPException(409, "Documento inexistente ou não está com erro.")
        return document

    @app.post("/api/chat")
    async def chat(body: ChatRequest, request: Request):
        if state.embedder.status != "ready":
            raise HTTPException(
                503, "O modelo de busca está carregando. Aguarde e tente novamente."
            )

        async def stream():
            try:
                # Cancellation of the response closes Ollama's HTTP stream and frees the lock.
                async with state.inference_lock:
                    embedding = await native_call(state.embedder.query, body.message)
                    sources = await state.db.search(
                        body.message, embedding, body.document_ids, settings.retrieval_top_k
                    )
                    messages, sources = build_prompt(
                        body.message,
                        [item.model_dump() for item in body.history],
                        sources,
                    )
                    yield event({"type": "sources", "sources": sources})
                    if not sources:
                        yield event(
                            {
                                "type": "token",
                                "content": (
                                    "Não encontrei informação suficiente nos documentos "
                                    "selecionados. Envie arquivos com texto sobre o assunto "
                                    "ou reformule a pergunta."
                                ),
                            }
                        )
                        yield event({"type": "done", "reason": "no_sources"})
                        return
                    async with asyncio.timeout(settings.generation_timeout_seconds):
                        async for chunk in state.llm.stream(messages):
                            if await request.is_disconnected():
                                return
                            yield event(chunk)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Chat generation failed")
                yield event(
                    {
                        "type": "error",
                        "message": (
                            "Não foi possível concluir a resposta. Confirme que o modelo Ollama "
                            "está disponível e tente novamente."
                        ),
                    }
                )

        return StreamingResponse(
            stream(),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return app


app = create_app()
