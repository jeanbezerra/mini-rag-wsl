import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from psycopg.errors import UniqueViolation

from rag.app import create_app
from rag.config import Settings


@pytest.fixture
def client(tmp_path):
    settings = Settings(data_dir=tmp_path, max_upload_mb=1)
    settings.uploads_dir.mkdir()
    state = SimpleNamespace(
        start=AsyncMock(),
        close=AsyncMock(),
        worker_error=False,
        db=SimpleNamespace(
            health=AsyncMock(return_value={"status": "ok", "version": "18.6"}),
            list_documents=AsyncMock(return_value=[]),
            add_document=AsyncMock(side_effect=lambda doc: {**doc, "status": "queued"}),
            delete_document=AsyncMock(return_value=True),
            retry_document=AsyncMock(return_value=None),
            search=AsyncMock(return_value=[]),
        ),
        embedder=SimpleNamespace(status="ready", error=None, query=Mock(return_value="[0]")),
        llm=SimpleNamespace(
            health=AsyncMock(return_value={"status": "missing", "name": "qwen3"}),
            stream=Mock(side_effect=AssertionError("No sources must skip LLM")),
        ),
        inference_lock=asyncio.Lock(),
    )
    with TestClient(create_app(settings, state)) as session:
        yield session, state, settings


def test_health_available_while_model_downloads(client):
    session, state, _ = client
    state.embedder.status = "loading"
    response = session.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["embedding"]["status"] == "loading"
    assert response.json()["model"]["status"] == "missing"


def test_upload_rejects_bad_extension_empty_and_large(client):
    session, _, settings = client
    assert session.post("/api/documents", files={"file": ("file.exe", b"x")}).status_code == 415
    assert session.post("/api/documents", files={"file": ("file.txt", b"")}).status_code == 422
    assert (
        session.post("/api/documents", files={"file": ("file.txt", b"x" * 1_100_000)}).status_code
        == 413
    )
    assert list(settings.uploads_dir.iterdir()) == []


def test_upload_persists_and_delete_removes_file(client):
    session, state, settings = client
    response = session.post("/api/documents", files={"file": ("../safe.txt", b"conteudo")})
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "safe.txt"
    path = settings.uploads_dir / data["id"]
    assert path.read_bytes() == b"conteudo"
    assert session.delete(f"/api/documents/{data['id']}").status_code == 204
    assert not path.exists()


def test_duplicate_cleans_uploaded_file(client):
    session, state, settings = client
    state.db.add_document.side_effect = UniqueViolation("duplicate")
    response = session.post("/api/documents", files={"file": ("file.txt", b"same")})
    assert response.status_code == 409
    assert list(settings.uploads_dir.iterdir()) == []


def test_chunked_upload_is_limited_without_content_length(client):
    session, _, settings = client
    boundary = "mini-rag-test-boundary"
    header = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
        'filename="file.txt"\r\nContent-Type: text/plain\r\n\r\n'
    ).encode()
    body = iter([header, b"x" * 1_100_000, f"\r\n--{boundary}--\r\n".encode()])
    response = session.post(
        "/api/documents",
        content=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    assert response.status_code == 413
    assert list(settings.uploads_dir.iterdir()) == []


def test_chat_without_sources_is_honest_and_skips_model(client):
    session, state, _ = client
    response = session.post("/api/chat", json={"message": "Qual a política?"})
    assert response.headers["content-type"].startswith("application/x-ndjson")
    events = [json.loads(line) for line in response.text.splitlines()]
    assert [item["type"] for item in events] == ["sources", "token", "done"]
    assert events[0]["sources"] == []
    assert events[-1]["reason"] == "no_sources"
    state.llm.stream.assert_not_called()


def test_chat_input_validates_and_requires_embedding(client):
    session, state, _ = client
    assert session.post("/api/chat", json={"message": " "}).status_code == 422
    assert (
        session.post("/api/chat", json={"message": "a", "document_ids": ["bad"]}).status_code == 422
    )
    assert (
        session.post(
            "/api/chat", json={"message": "a", "history": [{"role": "system", "content": "x"}]}
        ).status_code
        == 422
    )
    state.embedder.status = "loading"
    assert session.post("/api/chat", json={"message": "Olá"}).status_code == 503


def test_chat_streams_numbered_sources_and_model_answer(client):
    session, state, _ = client
    state.db.search.return_value = [
        {
            "id": uuid4(),
            "document_id": uuid4(),
            "name": "manual.pdf",
            "page": 2,
            "content": "Solicite reembolso no portal.",
            "score": 0.02,
        }
    ]

    async def answer(messages):
        assert "[1] manual.pdf" in messages[-1]["content"]
        yield {"type": "token", "content": "Solicite no portal [1]."}
        yield {"type": "done", "reason": "stop"}

    state.llm.stream = answer
    response = session.post("/api/chat", json={"message": "Como pedir reembolso?"})
    events = [json.loads(line) for line in response.text.splitlines()]
    assert events[0]["sources"][0]["id"] == "1"
    assert events[0]["sources"][0]["page"] == 2
    assert events[1]["content"].endswith("[1].")
    assert events[-1]["type"] == "done"


def test_chat_upstream_failure_becomes_error_event(client):
    session, state, _ = client
    state.db.search.side_effect = RuntimeError("sensitive database details")
    response = session.post("/api/chat", json={"message": "Qual a política?"})
    events = [json.loads(line) for line in response.text.splitlines()]
    assert events[-1]["type"] == "error"
    assert "sensitive" not in response.text


def test_retry_missing_or_non_error_document(client):
    session, _, _ = client
    assert session.post(f"/api/documents/{uuid4()}/retry").status_code == 409


def test_chat_document_selection_matches_configurable_library_capacity(client):
    session, state, _ = client
    document_ids = [str(uuid4()) for _ in range(201)]
    response = session.post(
        "/api/chat", json={"message": "O que dizem os documentos?", "document_ids": document_ids}
    )
    assert response.status_code == 200
    assert json.loads(response.text.splitlines()[-1])["reason"] == "no_sources"
    searched_ids = state.db.search.call_args.args[2]
    assert [str(document_id) for document_id in searched_ids] == document_ids
    too_many = [str(uuid4()) for _ in range(10001)]
    invalid = session.post(
        "/api/chat", json={"message": "Quais documentos?", "document_ids": too_many}
    )
    assert invalid.status_code == 422
    assert invalid.json()["detail"][0]["loc"] == ["body", "document_ids"]
    assert state.db.search.call_count == 1
