import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from rag.app import create_app
from rag.config import Settings


@pytest.fixture
def library_client(tmp_path):
    settings = Settings(data_dir=tmp_path)
    settings.uploads_dir.mkdir()
    state = SimpleNamespace(
        settings=settings,
        start=AsyncMock(),
        close=AsyncMock(),
        inference_lock=asyncio.Lock(),
        db=SimpleNamespace(
            library_summary=AsyncMock(return_value={"documents": {"total": 0}}),
            library_documents=AsyncMock(return_value={"documents": [], "total": 0}),
            library_document=AsyncMock(return_value=None),
            reindex_document=AsyncMock(return_value=None),
            library_performance=AsyncMock(return_value={"chat": {"samples": 0}}),
            search=AsyncMock(return_value=[]),
            record_chat_metrics=AsyncMock(),
        ),
        embedder=SimpleNamespace(status="ready", query=Mock(return_value="[0]")),
        llm=SimpleNamespace(stream=None),
    )
    with TestClient(create_app(settings, state)) as client:
        yield client, state


def test_library_parameters_are_validated_and_forwarded(library_client):
    client, state = library_client
    assert client.get("/api/library/summary").json()["documents"]["total"] == 0
    assert (
        client.get(
            "/api/library/documents?q=manual&status=ready&sort=chunks&page=2&page_size=7"
        ).status_code
        == 200
    )
    state.db.library_documents.assert_awaited_once_with("manual", "ready", "chunks", 2, 7)
    for query in ("sort=DROP", "status=finished", "page=0", "page_size=101"):
        assert client.get(f"/api/library/documents?{query}").status_code == 422
    assert client.get("/api/library/performance?model=small:1b").status_code == 200
    state.db.library_performance.assert_awaited_once_with("small:1b")
    identifier = uuid4()
    assert client.get(f"/api/library/documents/{identifier}?page=2&page_size=5").status_code == 404
    state.db.library_document.assert_awaited_once_with(identifier, 2, 5)
    assert client.get(f"/api/library/documents/{identifier}?page_size=51").status_code == 422


def test_reindex_requires_original_file_and_ready_transition(library_client):
    client, state = library_client
    identifier = uuid4()
    path = state.settings.uploads_dir / str(identifier)
    assert client.post(f"/api/library/documents/{identifier}/reindex").status_code == 404
    state.db.reindex_document.assert_not_awaited()
    path.write_text("original preservado", encoding="utf-8")
    assert client.post(f"/api/library/documents/{identifier}/reindex").status_code == 409
    state.db.reindex_document.return_value = {"id": str(identifier), "status": "queued"}
    accepted = client.post(f"/api/library/documents/{identifier}/reindex")
    assert accepted.status_code == 202 and accepted.json()["status"] == "queued"
    assert path.read_text(encoding="utf-8") == "original preservado"


def source():
    return {
        "id": uuid4(),
        "document_id": uuid4(),
        "name": "manual.txt",
        "page": None,
        "content": "Resposta confidencial para a pergunta privada.",
        "score": 0.03,
    }


def test_chat_records_real_stages_and_settings_without_conversation_text(library_client):
    client, state = library_client

    async def search(*args):
        await asyncio.sleep(0.04)
        return [source()]

    async def answer(messages):
        await asyncio.sleep(0.04)
        yield {"type": "token", "content": "Texto da resposta privada [1]."}
        yield {"type": "done", "tokens": 4, "tokens_per_second": 8}

    state.db.search.side_effect = search
    state.llm.stream = answer
    response = client.post("/api/chat", json={"message": "Pergunta privada?"})
    assert response.status_code == 200
    metrics = state.db.record_chat_metrics.call_args.args[0]
    assert metrics["outcome"] == "completed"
    assert metrics["duration_ms"] >= metrics["first_token_ms"] >= metrics["search_ms"] >= 10
    assert metrics["output_tokens"] == 4 and metrics["tokens_per_second"] == 8
    assert metrics["source_count"] == 1
    assert metrics["settings"]["cpu_threads"] == state.settings.cpu_threads
    encoded = json.dumps(metrics, default=str)
    assert "privada" not in encoded and "database_url" not in encoded
    assert not state.inference_lock.locked()


def test_no_sources_and_failed_telemetry_do_not_corrupt_the_response(library_client):
    client, state = library_client
    state.db.record_chat_metrics.side_effect = RuntimeError("private connection failure")
    response = client.post("/api/chat", json={"message": "Uma pergunta?"})
    events = [json.loads(line) for line in response.text.splitlines()]
    assert events[-1] == {"type": "done", "reason": "no_sources"}
    assert "private" not in response.text
    metrics = state.db.record_chat_metrics.call_args.args[0]
    assert metrics["outcome"] == "no_sources"
    assert (
        metrics["first_token_ms"]
        is metrics["output_tokens"]
        is metrics["tokens_per_second"]
        is None
    )
    assert not state.inference_lock.locked()


def test_failed_generation_after_partial_answer_is_not_completed(library_client):
    client, state = library_client
    state.db.search.return_value = [source()]

    async def answer(messages):
        yield {"type": "token", "content": "Parcial"}
        raise RuntimeError("Ollama stream interrupted")

    state.llm.stream = answer
    response = client.post("/api/chat", json={"message": "Uma pergunta?"})
    assert json.loads(response.text.splitlines()[-1])["type"] == "error"
    metrics = state.db.record_chat_metrics.call_args.args[0]
    assert metrics["outcome"] == "error" and metrics["first_token_ms"] is not None
    assert metrics["tokens_per_second"] is None
