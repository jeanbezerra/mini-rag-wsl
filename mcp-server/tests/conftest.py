import asyncio
import socket
from contextlib import asynccontextmanager

import anyio
import httpx
import pytest
import uvicorn

from rag_mcp.app import create_app
from rag_mcp.config import Settings

DOC_ID = "45222966-e22e-4a80-ad7b-c8db14650bb1"
CHUNK_ID = "45222966-e22e-4a80-ad7b-c8db14650bb2"
DOCUMENT = {
    "id": DOC_ID,
    "name": "Guia.pdf",
    "size_bytes": 1000,
    "status": "ready",
    "chunk_count": 1,
    "created_at": "2026-10-23T12:00:00Z",
    "extension": ".pdf",
    "error": "private exception deliberately filtered",
}
CHUNK = {
    "id": CHUNK_ID,
    "ordinal": 0,
    "page": 3,
    "content": "A configuração do Java protege a aplicação.",
    "token_count": 12,
    "char_count": 43,
}


class Backend:
    def __init__(self):
        self.requests = []
        self.status = 200
        self.payload_override = None
        self.raise_connection = False
        self.wait = None
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def __call__(self, request):
        self.requests.append(request)
        if self.raise_connection:
            raise httpx.ConnectError("secret postgres://secret@private:8000", request=request)
        if self.wait is not None:
            self.started.set()
            try:
                await self.wait.wait()
            except asyncio.CancelledError:
                self.cancelled.set()
                raise
        if self.status != 200:
            return httpx.Response(self.status, json={"detail": "private database password"})
        if self.payload_override is not None:
            return httpx.Response(200, json=self.payload_override)
        path = request.url.path
        if path == "/api/search":
            import json

            body = json.loads(request.content)
            sources = (
                []
                if body["document_ids"] == []
                else [
                    {
                        "id": CHUNK_ID,
                        "document_id": DOC_ID,
                        "name": DOCUMENT["name"],
                        "page": CHUNK["page"],
                        "content": CHUNK["content"],
                        "score": 0.03,
                    }
                ]
            )
            value = {
                "query": body["query"],
                "sources": sources,
                "count": len(sources),
                "limit": body["limit"] or 6,
                "score_type": "rrf",
                "embedding_model": "minilm",
            }
        elif path == "/api/library/documents":
            value = {"documents": [DOCUMENT], "total": 1, "page": 1, "page_size": 20}
        elif path == f"/api/library/documents/{DOC_ID}":
            value = {
                "document": DOCUMENT,
                "chunks": {"items": [CHUNK], "total": 1, "page": 1, "page_size": 12},
                "indexing": {"histogram": list(range(129))},
                "ingestion": {"settings": {"secret": "not public"}},
            }
        elif path == "/api/health":
            value = {
                "status": "ok",
                "database": {"status": "ok", "version": "18.6"},
                "model": {"status": "ready", "name": "qwen3:1.7b"},
                "embedding": {"status": "ready", "name": "minilm", "error": "secret"},
                "worker": {"status": "ok"},
                "limits": {"max_pdf_pages": 800},
                "cpu_threads": 4,
            }
        elif path == "/api/library/summary":
            value = {
                "documents": {"total": 1, "ready": 1},
                "storage_bytes": 1000,
                "chunks": 1,
                "formats": [{"extension": ".pdf", "documents": 1, "size_bytes": 1000}],
                "largest_documents": [{"id": DOC_ID, "name": "Guia.pdf", "chunk_count": 1}],
                "indexing": {"measured_documents": 1, "histogram": list(range(129))},
            }
        elif path == "/api/library/performance":
            value = {
                "window": {"limit": 500, "from": None, "to": None},
                "models": ["qwen3:1.7b"],
                "chat": {"samples": 30, "first_token_ms": {"p50": 250, "p95": 500}},
                "ingestion": {"samples": 1},
                "recent_chat": [{"id": str(i), "duration_ms": i} for i in range(30)],
                "recent_ingestion": [{"id": str(i)} for i in range(30)],
            }
        else:
            return httpx.Response(404)
        return httpx.Response(200, json=value)


@asynccontextmanager
async def serve(app):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    sock.setblocking(False)
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="on"))
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        with anyio.fail_after(10):
            while not server.started:
                if task.done():
                    await task
                await anyio.sleep(0.01)
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        with anyio.fail_after(10):
            await task
        sock.close()


@pytest.fixture
async def running():
    backend = Backend()
    app = create_app(Settings(), backend_transport=httpx.MockTransport(backend))
    async with serve(app) as url:
        yield url, backend, app
