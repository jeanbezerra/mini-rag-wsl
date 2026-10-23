import asyncio
import json
from contextlib import asynccontextmanager

import anyio
import httpx
import pytest
from conftest import DOC_ID
from mcp import Client, ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client

from rag_mcp.app import MAX_REQUEST_BYTES


@asynccontextmanager
async def connect(url, kind):
    transport = sse_client(url + "/sse") if kind == "sse" else streamable_http_client(url + "/mcp")
    async with transport as streams, ClientSession(streams[0], streams[1]) as session:
        initialized = await session.initialize()
        assert initialized.server_info.name == "Mini RAG"
        yield session


@pytest.mark.parametrize("kind", ["sse", "http"])
async def test_sdk_initialize_discover_and_call_all_tools(running, kind):
    url, backend, app = running
    async with connect(url, kind) as session:
        tools = (await session.list_tools()).tools
        assert len(tools) == 6
        assert {tool.name for tool in tools} == {
            "search_documents",
            "list_documents",
            "get_document_chunks",
            "get_rag_status",
            "get_library_summary",
            "get_model_performance",
        }
        for tool in tools:
            assert tool.output_schema["type"] == "object"
            assert tool.annotations.read_only_hint
            assert tool.annotations.idempotent_hint
            assert tool.annotations.destructive_hint is False
            assert tool.annotations.open_world_hint is False
        result = await session.call_tool(
            "search_documents", {"query": "segurança Java", "limit": 2}
        )
        assert not result.is_error
        data = result.structured_content
        assert data["score_type"] == "rrf"
        assert data["sources"][0]["document_id"] == DOC_ID
        assert data["sources"][0]["page"] == 3
        assert json.loads(result.content[0].text) == data
        no_files = await session.call_tool(
            "search_documents", {"query": "Java", "document_ids": []}
        )
        assert no_files.structured_content["sources"] == []
        listing = await session.call_tool("list_documents", {"query": "Guia", "status": "ready"})
        assert listing.structured_content["documents"][0]["id"] == DOC_ID
        assert "error" not in listing.structured_content["documents"][0]
        chunks = await session.call_tool("get_document_chunks", {"document_id": DOC_ID})
        assert set(chunks.structured_content) == {"document", "chunks"}
        health = await session.call_tool("get_rag_status", {})
        assert "secret" not in str(health.structured_content)
        summary = await session.call_tool("get_library_summary", {})
        assert "histogram" not in summary.structured_content["indexing"]
        performance = await session.call_tool("get_model_performance", {"history_limit": 2})
        assert len(performance.structured_content["recent_chat"]) == 2
        assert len(performance.structured_content["recent_ingestion"]) == 2
        assert performance.structured_content["chat"]["samples"] == 30
        assert len(backend.requests) == 7
    assert app.state.gateway.client is not None


@pytest.mark.parametrize("kind", ["sse", "http"])
async def test_schema_errors_do_not_reach_backend(running, kind):
    url, backend, _ = running
    invalid = [
        ("search_documents", {"query": "Java", "limit": 13}),
        ("search_documents", {"query": "Java", "limit": "2"}),
        ("search_documents", {"query": " "}),
        ("search_documents", {"query": "é" * 751}),
        ("search_documents", {"query": "Java", "document_ids": ["../etc/passwd"]}),
        ("get_document_chunks", {"document_id": "../etc/passwd"}),
        ("list_documents", {"status": "deleted"}),
        ("list_documents", {"page": 0}),
        ("list_documents", {"page_size": 101}),
        ("get_model_performance", {"history_limit": 21}),
    ]
    async with connect(url, kind) as session:
        for name, args in invalid:
            result = await session.call_tool(name, args)
            assert result.is_error, (name, args)
        assert not backend.requests


@pytest.mark.parametrize("kind", ["sse", "http"])
async def test_backend_failures_are_tool_errors_without_private_details(running, kind):
    url, backend, _ = running
    async with connect(url, kind) as session:
        for status in [404, 409, 422, 500, 503, 302]:
            backend.status = status
            result = await session.call_tool("get_document_chunks", {"document_id": DOC_ID})
            assert result.is_error
            assert "private" not in result.content[0].text
        backend.status = 200
        backend.raise_connection = True
        result = await session.call_tool("get_rag_status", {})
        assert result.is_error
        assert "secret" not in result.content[0].text
        backend.raise_connection = False
        backend.payload_override = {"wrong": "schema"}
        result = await session.call_tool("get_rag_status", {})
        assert result.is_error
        assert "incompatível" in result.content[0].text


@pytest.mark.parametrize(
    "path,method",
    [
        ("/sse", "GET"),
        ("/messages/", "POST"),
        ("/mcp", "POST"),
        ("/mcp", "GET"),
        ("/healthz", "GET"),
    ],
)
async def test_host_origin_guards_before_transport_handshake(running, path, method):
    url, _, _ = running
    async with httpx.AsyncClient() as client:
        invalid_host = await client.request(method, url + path, headers={"host": "evil.test"})
        assert invalid_host.status_code == 421
        for origin in [
            "https://evil.test",
            "null",
            "http://localhost:1@evil.test",
            "http://localhost:bad",
        ]:
            invalid_origin = await client.request(method, url + path, headers={"origin": origin})
            assert invalid_origin.status_code == 403
        assert "access-control-allow-origin" not in invalid_origin.headers


@pytest.mark.parametrize("path", ["/mcp", "/messages/?session_id=unknown"])
async def test_body_size_limit_header_and_chunked(running, path):
    url, _, _ = running
    async with httpx.AsyncClient() as client:
        result = await client.post(
            url + path,
            content=b"a" * (MAX_REQUEST_BYTES + 1),
            headers={"content-type": "application/json"},
        )
        assert result.status_code == 413

        async def body():
            yield b"a" * (MAX_REQUEST_BYTES // 2)
            yield b"a" * (MAX_REQUEST_BYTES // 2 + 1)

        result = await client.post(
            url + path, content=body(), headers={"content-type": "application/json"}
        )
        assert result.status_code == 413


@pytest.mark.parametrize("kind", ["sse", "http"])
async def test_sdk_cancellation_releases_backend_request(running, kind):
    url, backend, app = running
    backend.wait = asyncio.Event()
    async with connect(url, kind) as session:
        pending = asyncio.create_task(session.call_tool("search_documents", {"query": "Java"}))
        with anyio.fail_after(5):
            await backend.started.wait()
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        with anyio.fail_after(5):
            await backend.cancelled.wait()
        assert app.state.gateway.slots.borrowed_tokens == 0
        backend.wait = None
        healthy = await session.call_tool("get_rag_status", {})
        assert not healthy.is_error


async def test_current_sdk_client_uses_modern_protocol(running):
    url, _, _ = running
    async with Client(url + "/mcp") as client:
        assert len((await client.list_tools()).tools) == 6
        result = await client.call_tool("search_documents", {"query": "Java"})
        assert result.structured_content["limit"] == 6
        assert not result.is_error


@pytest.mark.parametrize("kind", ["sse", "http"])
async def test_legacy_chunks_have_unknown_token_measurements(running, kind):
    url, backend, _ = running
    from conftest import CHUNK, DOCUMENT

    backend.payload_override = {
        "document": DOCUMENT,
        "chunks": {
            "items": [{**CHUNK, "token_count": None}],
            "total": 1,
            "page": 1,
            "page_size": 12,
        },
    }
    async with connect(url, kind) as session:
        result = await session.call_tool("get_document_chunks", {"document_id": DOC_ID})
        assert not result.is_error
        assert result.structured_content["chunks"]["items"][0]["token_count"] is None


@pytest.mark.parametrize("kind", ["sse", "http"])
async def test_long_whitespace_evidence_is_preserved_in_search_and_chunks(running, kind):
    url, backend, _ = running
    from conftest import CHUNK, CHUNK_ID, DOCUMENT

    content = "primeiro" + "\n" * 10000 + "último"
    source = {
        "id": CHUNK_ID,
        "document_id": DOC_ID,
        "name": DOCUMENT["name"],
        "page": None,
        "content": content,
        "score": 0.03,
    }
    async with connect(url, kind) as session:
        backend.payload_override = {
            "query": "primeiro",
            "sources": [source],
            "count": 1,
            "limit": 6,
            "score_type": "rrf",
            "embedding_model": "minilm",
        }
        search = await session.call_tool("search_documents", {"query": "primeiro"})
        assert not search.is_error
        assert search.structured_content["sources"][0]["content"] == content
        backend.payload_override = {
            "document": DOCUMENT,
            "chunks": {
                "items": [
                    {**CHUNK, "content": content, "token_count": 6, "char_count": len(content)}
                ],
                "total": 1,
                "page": 1,
                "page_size": 12,
            },
        }
        chunks = await session.call_tool("get_document_chunks", {"document_id": DOC_ID})
        assert not chunks.is_error
        assert chunks.structured_content["chunks"]["items"][0]["content"] == content


async def test_streamable_legacy_session_lifecycle_and_get_sse(running):
    url, _, _ = running
    headers = {"accept": "application/json, text/event-stream", "content-type": "application/json"}
    initialize = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "integration-test", "version": "1.0"},
        },
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(url + "/mcp", json=initialize, headers=headers)
        assert response.status_code == 200
        session_id = response.headers["mcp-session-id"]
        headers.update({"mcp-session-id": session_id, "mcp-protocol-version": "2025-11-25"})
        initialized = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        assert (
            await client.post(url + "/mcp", json=initialized, headers=headers)
        ).status_code == 202
        async with client.stream("GET", url + "/mcp", headers=headers) as stream:
            assert stream.status_code == 200
            assert stream.headers["content-type"].startswith("text/event-stream")
        assert (await client.delete(url + "/mcp", headers=headers)).status_code == 200
        request = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
        assert (await client.post(url + "/mcp", json=request, headers=headers)).status_code == 404
