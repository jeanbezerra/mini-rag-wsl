import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from rag.app import SearchRequest, create_app
from rag.config import Settings


def connection(disconnected: asyncio.Event | None = None) -> Request:
    closed = disconnected or asyncio.Event()

    async def receive():
        await closed.wait()
        return {"type": "http.disconnect"}

    return Request({"type": "http"}, receive)


@pytest.fixture
def search_state(tmp_path):
    settings = Settings(data_dir=tmp_path)
    return SimpleNamespace(
        settings=settings,
        start=AsyncMock(),
        close=AsyncMock(),
        inference_lock=asyncio.Lock(),
        db=SimpleNamespace(search=AsyncMock(return_value=[]), settings=settings),
        embedder=SimpleNamespace(status="ready", query=Mock(return_value="[0.1]")),
        llm=SimpleNamespace(stream=Mock(side_effect=AssertionError("Search must skip LLM"))),
    )


@pytest.fixture
def search_client(search_state):
    with TestClient(create_app(search_state.settings, search_state)) as client:
        yield client, search_state


def test_search_returns_full_sources_with_stable_ids_and_no_generation(search_client, monkeypatch):
    client, state = search_client
    source = {
        "id": uuid4(),
        "document_id": uuid4(),
        "name": "manual.pdf",
        "page": 42,
        "content": "Trecho completo sem corte pelo orçamento do prompt. " * 100,
        "score": 0.03278688524590164,
    }
    state.db.search.return_value = [source]
    prompt = Mock(side_effect=AssertionError("Search must skip prompt generation"))
    monkeypatch.setattr("rag.app.build_prompt", prompt)
    response = client.post("/api/search", json={"query": "  segurança Java  "})
    assert response.status_code == 200
    data = response.json()
    assert data == {
        "query": "segurança Java",
        "sources": [{**source, "id": str(source["id"]), "document_id": str(source["document_id"])}],
        "count": 1,
        "limit": state.settings.retrieval_top_k,
        "score_type": "rrf",
        "embedding_model": state.settings.embedding_model,
    }
    state.embedder.query.assert_called_once_with("segurança Java")
    state.db.search.assert_awaited_once_with(
        "segurança Java", "[0.1]", None, state.settings.retrieval_top_k
    )
    state.llm.stream.assert_not_called()
    prompt.assert_not_called()
    assert not state.inference_lock.locked()


def test_text_sources_without_page_numbers_are_valid(search_client):
    client, state = search_client
    state.db.search.return_value = [
        {
            "id": uuid4(),
            "document_id": uuid4(),
            "name": "manual.txt",
            "page": None,
            "content": "Texto indexado sem numeração de página.",
            "score": 0.016,
        }
    ]
    response = client.post("/api/search", json={"query": "manual"})
    assert response.status_code == 200
    assert response.json()["sources"][0]["page"] is None


@pytest.mark.parametrize("limit", [1, 12, None])
def test_explicit_and_default_search_limits(search_client, limit):
    client, state = search_client
    state.settings = state.settings.model_copy(update={"retrieval_top_k": 9})
    response = client.post("/api/search", json={"query": "segurança", "limit": limit})
    assert response.status_code == 200
    expected = 9 if limit is None else limit
    assert response.json()["limit"] == expected
    assert state.db.search.call_args.args[3] == expected


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"query": ""},
        {"query": " \t\n "},
        {"query": 123},
        {"query": True},
        {"query": None},
        {"query": "a" * 2001},
        {"query": "á" * 751},
        {"query": "😀" * 376},
        {"query": "segurança", "limit": 0},
        {"query": "segurança", "limit": 13},
        {"query": "segurança", "limit": True},
        {"query": "segurança", "limit": "6"},
        {"query": "segurança", "limit": 6.0},
        {"query": "segurança", "document_ids": ["invalid"]},
        {"query": "segurança", "document_ids": [1]},
        {"query": "segurança", "document_ids": "invalid"},
        {"query": "segurança", "document_ids": [None]},
        {"query": "segurança", "unknown": True},
    ],
)
def test_invalid_search_input_never_touches_cpu_or_database(search_client, body):
    client, state = search_client
    assert client.post("/api/search", json=body).status_code == 422
    state.embedder.query.assert_not_called()
    state.db.search.assert_not_awaited()


def test_query_utf8_boundary_and_document_capacity(search_client):
    client, state = search_client
    document_ids = [str(uuid4()) for _ in range(10000)]
    response = client.post("/api/search", json={"query": "á" * 750, "document_ids": document_ids})
    assert response.status_code == 200
    assert [str(item) for item in state.db.search.call_args.args[2]] == document_ids
    response = client.post(
        "/api/search", json={"query": "segurança", "document_ids": [*document_ids, str(uuid4())]}
    )
    assert response.status_code == 422
    assert state.db.search.await_count == 1


@pytest.mark.parametrize("ids", [None, []])
def test_no_document_filter_and_empty_selection_remain_distinct(search_client, ids):
    client, state = search_client
    response = client.post("/api/search", json={"query": "segurança", "document_ids": ids})
    assert response.status_code == 200
    assert response.json()["sources"] == [] and response.json()["count"] == 0
    assert state.db.search.call_args.args[2] == ids


@pytest.mark.parametrize("status", ["loading", "error"])
def test_search_requires_ready_embedder_without_waiting_for_cpu(search_client, status):
    client, state = search_client
    state.embedder.status = status
    response = client.post("/api/search", json={"query": "segurança"})
    assert response.status_code == 503
    assert "modelo de busca" in response.json()["detail"]
    state.embedder.query.assert_not_called()
    state.db.search.assert_not_awaited()
    assert not state.inference_lock.locked()


@pytest.mark.parametrize("failure", ["embedding", "database"])
def test_search_failures_are_safe_and_release_cpu_lock(search_client, failure):
    client, state = search_client
    error = RuntimeError("secret PostgreSQL URL or native model path")
    if failure == "embedding":
        state.embedder.query.side_effect = error
    else:
        state.db.search.side_effect = error
    response = client.post("/api/search", json={"query": "segurança"})
    assert response.status_code == 503
    assert "secret" not in response.text
    assert not state.inference_lock.locked()
    state.llm.stream.assert_not_called()


async def test_search_reads_active_settings_after_waiting_and_holds_lock_through_database(
    search_state,
):
    state = search_state
    app = create_app(state.settings, state)
    entered, finish = asyncio.Event(), asyncio.Event()

    async def search(query, embedding, ids, limit):
        assert state.inference_lock.locked()
        assert limit == 9 and state.db.settings.min_similarity == 0.79
        entered.set()
        await finish.wait()
        return []

    state.db.search.side_effect = search
    await state.inference_lock.acquire()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        operation = asyncio.create_task(client.post("/api/search", json={"query": "segurança"}))
        try:
            await asyncio.sleep(0.01)
            state.embedder.query.assert_not_called()
            active = state.settings.model_copy(
                update={"retrieval_top_k": 9, "min_similarity": 0.79}
            )
            state.settings = state.db.settings = active
            state.inference_lock.release()
            await asyncio.wait_for(entered.wait(), timeout=2)
            assert state.inference_lock.locked()
            finish.set()
            response = await operation
            assert response.status_code == 200
            assert response.json()["limit"] == 9
        finally:
            finish.set()
            if not operation.done():
                operation.cancel()
            await asyncio.gather(operation, return_exceptions=True)


async def test_search_rechecks_embedder_after_waiting_for_settings_change(search_state):
    state = search_state
    app = create_app(state.settings, state)
    await state.inference_lock.acquire()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        operation = asyncio.create_task(client.post("/api/search", json={"query": "segurança"}))
        await asyncio.sleep(0.01)
        state.embedder.status = "error"
        state.inference_lock.release()
        response = await operation
    assert response.status_code == 503
    state.embedder.query.assert_not_called()
    assert not state.inference_lock.locked()


async def test_busy_queue_is_bounded_without_releasing_another_operation_lock(
    search_state, monkeypatch
):
    state = search_state
    monkeypatch.setattr("rag.app.SEARCH_QUEUE_TIMEOUT_SECONDS", 0.01)
    app = create_app(state.settings, state)
    await state.inference_lock.acquire()
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            response = await client.post("/api/search", json={"query": "segurança"})
        assert response.status_code == 503
        assert "ocupada" in response.json()["detail"]
        assert state.inference_lock.locked()
        state.embedder.query.assert_not_called()
    finally:
        state.inference_lock.release()


async def test_cancelled_search_keeps_cpu_lock_until_native_embedding_finishes(search_state):
    state = search_state
    entered, finish = threading.Event(), threading.Event()

    def embed(query):
        entered.set()
        finish.wait(timeout=3)
        return "[0.1]"

    state.embedder.query.side_effect = embed
    app = create_app(state.settings, state)
    # Exercise the endpoint directly to cancel the owning task, as ASGI does when
    # its caller disconnects, without TestClient's independent request thread.
    endpoint = next(route.endpoint for route in app.routes if route.path == "/api/search")
    request = connection()
    operation = asyncio.create_task(endpoint(SearchRequest(query="segurança"), request))
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        operation.cancel()
        await asyncio.sleep(0.01)
        assert state.inference_lock.locked()
        state.db.search.assert_not_awaited()
    finally:
        finish.set()
    with pytest.raises(asyncio.CancelledError):
        await operation
    assert not state.inference_lock.locked()
    state.db.search.assert_not_awaited()


async def test_cancelled_queue_does_not_unlock_running_operation(search_state):
    state = search_state
    app = create_app(state.settings, state)
    endpoint = next(route.endpoint for route in app.routes if route.path == "/api/search")
    await state.inference_lock.acquire()
    request = connection()
    operation = asyncio.create_task(endpoint(SearchRequest(query="segurança"), request))
    try:
        await asyncio.sleep(0.01)
        operation.cancel()
        with pytest.raises(asyncio.CancelledError):
            await operation
        assert state.inference_lock.locked()
        state.embedder.query.assert_not_called()
    finally:
        state.inference_lock.release()


async def test_socket_disconnect_removes_queued_search_without_unlocking_other_work(search_state):
    state = search_state
    app = create_app(state.settings, state)
    received = asyncio.Event()
    disconnected = asyncio.Event()

    async def receive():
        await disconnected.wait()
        return {"type": "http.disconnect"}

    request = Request({"type": "http"}, receive)
    # Signal that retrieval tried to join the shared CPU queue.
    original_acquire = state.inference_lock.acquire

    async def acquire():
        received.set()
        return await original_acquire()

    await original_acquire()
    state.inference_lock.acquire = acquire
    endpoint = next(route.endpoint for route in app.routes if route.path == "/api/search")
    operation = asyncio.create_task(endpoint(SearchRequest(query="segurança"), request))
    try:
        await asyncio.wait_for(received.wait(), timeout=2)
        disconnected.set()
        with pytest.raises(HTTPException) as result:
            await asyncio.wait_for(operation, timeout=2)
        assert result.value.status_code == 499
        assert state.inference_lock.locked()
        state.embedder.query.assert_not_called()
        state.db.search.assert_not_awaited()
    finally:
        state.inference_lock.release()
        if not operation.done():
            operation.cancel()
        await asyncio.gather(operation, return_exceptions=True)


async def test_socket_disconnect_during_embedding_waits_for_cpu_thread_before_unlocking(
    search_state,
):
    state = search_state
    entered, finish = threading.Event(), threading.Event()
    disconnected = asyncio.Event()

    def embed(query):
        entered.set()
        finish.wait(timeout=3)
        return "[0.1]"

    state.embedder.query.side_effect = embed
    request = connection(disconnected)
    app = create_app(state.settings, state)
    endpoint = next(route.endpoint for route in app.routes if route.path == "/api/search")
    operation = asyncio.create_task(endpoint(SearchRequest(query="segurança"), request))
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        disconnected.set()
        # Allow the disconnect watcher to request cancellation while native code runs.
        await asyncio.sleep(0.01)
        assert state.inference_lock.locked()
        assert not operation.done()
        state.db.search.assert_not_awaited()
    finally:
        finish.set()
    with pytest.raises(HTTPException) as result:
        await operation
    assert result.value.status_code == 499
    assert not state.inference_lock.locked()
    state.db.search.assert_not_awaited()


async def test_real_receive_channel_detects_disconnect_through_http_middleware(search_state):
    state = search_state
    app = create_app(state.settings, state)
    disconnected, queued = asyncio.Event(), asyncio.Event()
    delivered = False
    sent = []
    original_acquire = state.inference_lock.acquire

    async def acquire():
        queued.set()
        return await original_acquire()

    async def receive():
        nonlocal delivered
        if not delivered:
            delivered = True
            return {"type": "http.request", "body": b'{"query":"Java"}', "more_body": False}
        await disconnected.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/search",
        "raw_path": b"/api/search",
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"localhost"), (b"content-type", b"application/json")],
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 8000),
    }
    await original_acquire()
    state.inference_lock.acquire = acquire
    operation = asyncio.create_task(app(scope, receive, send))
    try:
        await asyncio.wait_for(queued.wait(), timeout=2)
        disconnected.set()
        await asyncio.wait_for(operation, timeout=2)
        assert state.inference_lock.locked()
        state.embedder.query.assert_not_called()
        state.db.search.assert_not_awaited()
        assert any(message.get("status") == 499 for message in sent)
    finally:
        state.inference_lock.release()
        if not operation.done():
            operation.cancel()
        await asyncio.gather(operation, return_exceptions=True)
