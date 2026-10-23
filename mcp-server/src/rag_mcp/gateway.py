import json
from contextlib import asynccontextmanager
from typing import Any

import anyio
import httpx
from mcp.server.mcpserver.exceptions import ToolError

from rag_mcp.config import Settings

MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class Gateway:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings
        self.transport = transport
        self.client: httpx.AsyncClient | None = None
        self.slots = anyio.CapacityLimiter(4)

    @asynccontextmanager
    async def lifespan(self):
        async with httpx.AsyncClient(
            base_url=self.settings.api_base_url,
            timeout=httpx.Timeout(self.settings.request_timeout_seconds, connect=5),
            limits=httpx.Limits(max_connections=4, max_keepalive_connections=4),
            transport=self.transport,
            trust_env=False,
            follow_redirects=False,
        ) as client:
            self.client = client
            try:
                yield
            finally:
                self.client = None

    async def request(self, method: str, path: str, **kwargs: Any) -> dict:
        try:
            self.slots.acquire_nowait()
        except anyio.WouldBlock as exc:
            raise ToolError("O RAG está ocupado. Tente novamente em instantes.") from exc
        try:
            if self.client is None:
                raise ToolError("O serviço RAG está indisponível. Tente novamente.")
            with anyio.fail_after(self.settings.request_timeout_seconds):
                async with self.client.stream(method, path, **kwargs) as response:
                    if response.status_code == 404:
                        raise ToolError("Documento não encontrado. Atualize a lista de documentos.")
                    if response.status_code in {409, 429}:
                        raise ToolError("O RAG está ocupado. Tente novamente em instantes.")
                    if response.status_code in {400, 422}:
                        raise ToolError(
                            "Consulta inválida. Confira os argumentos e tente novamente."
                        )
                    if not 200 <= response.status_code < 300:
                        raise ToolError("A API do RAG está indisponível. Tente novamente.")
                    chunks = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(chunks) + len(chunk) > MAX_RESPONSE_BYTES:
                            raise ToolError("Resposta muito grande. Reduza a página da consulta.")
                        chunks.extend(chunk)
                    value = json.loads(chunks)
                    if not isinstance(value, dict):
                        raise ValueError("Expected object")
                    return value
        except (httpx.TimeoutException, TimeoutError) as exc:
            raise ToolError(
                "O RAG demorou para responder. Tente novamente após a ingestão."
            ) from exc
        except httpx.HTTPError as exc:
            raise ToolError("Não foi possível acessar a API do RAG. Verifique o serviço.") from exc
        except (ValueError, TypeError) as exc:
            raise ToolError("A API do RAG retornou uma resposta inválida.") from exc
        finally:
            self.slots.release()
