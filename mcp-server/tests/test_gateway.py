import asyncio

import anyio
import httpx
import pytest
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import ValidationError

from rag_mcp.config import Settings
from rag_mcp.gateway import MAX_RESPONSE_BYTES, Gateway
from rag_mcp.security import local_authority


@pytest.mark.parametrize(
    "url",
    [
        "file:///tmp/db",
        "http://user:secret@localhost",
        "http://api:bad",
        "http://api:8000/path",
        "http://api?token=x",
    ],
)
def test_only_configured_api_origin_is_accepted(url):
    with pytest.raises(ValidationError):
        Settings(api_base_url=url)


@pytest.mark.parametrize("host", ["localhost", "localhost:8001", "127.0.0.1:123", "[::1]:8001"])
def test_local_hosts(host):
    assert local_authority(host)
    assert local_authority("http://" + host, origin=True)


@pytest.mark.parametrize(
    "host",
    [
        "evil",
        "localhost.evil:8001",
        "localhost:bad",
        "localhost:",
        "localhost:8001/",
        "localhost:8001@evil",
        "localhost:8001?",
        "localhost:8001#",
        "",
        "localhost:0",
    ],
)
def test_nonlocal_or_malformed_host(host):
    assert not local_authority(host)


async def test_lifespan_closes_http_pool_and_bounds_total_time():
    cancelled = asyncio.Event()

    async def slow(request):
        try:
            await anyio.sleep_forever()
        finally:
            cancelled.set()

    settings = Settings().model_copy(update={"request_timeout_seconds": 0.03})
    gateway = Gateway(settings, httpx.MockTransport(slow))
    async with gateway.lifespan():
        client = gateway.client
        with pytest.raises(ToolError, match="demorou"):
            await gateway.request("GET", "/api/health")
        assert cancelled.is_set()
        assert gateway.slots.borrowed_tokens == 0
    assert gateway.client is None
    assert client.is_closed


async def test_api_response_size_bound():
    gateway = Gateway(
        Settings(),
        httpx.MockTransport(
            lambda request: httpx.Response(200, content=b"a" * (MAX_RESPONSE_BYTES + 1))
        ),
    )
    async with gateway.lifespan():
        with pytest.raises(ToolError, match="muito grande"):
            await gateway.request("GET", "/api/health")


async def test_no_unbounded_wait_queue():
    gateway = Gateway(Settings())
    for _ in range(4):
        gateway.slots.acquire_on_behalf_of_nowait(object())
    with pytest.raises(ToolError, match="ocupado"):
        await gateway.request("GET", "/api/health")
