import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from rag.app import create_app
from rag.config import PublicSettings, Settings
from rag.runtime import Runtime


@pytest.fixture
def configured_client(tmp_path):
    state = Runtime(Settings(data_dir=tmp_path, cpu_threads=2))
    state.start, state.close = AsyncMock(), AsyncMock()
    state.settings.uploads_dir.mkdir()
    state.db.health = AsyncMock(return_value={"status": "ok", "version": "18.6"})

    async def persist(revision, values):
        return {"revision": revision + 1, "values": values, "updated_at": datetime.now(UTC)}

    state.db.save_runtime_settings = AsyncMock(side_effect=persist)
    state.llm.health = AsyncMock(return_value={"status": "ready", "name": "qwen3"})
    state.llm.models = AsyncMock(return_value=[{"name": "outro:1b", "size_bytes": 1}])
    state.llm.selectable_model = AsyncMock(side_effect=lambda name: name == "outro:1b")
    with TestClient(create_app(state.settings, state)) as client:
        yield client, state


@pytest.mark.parametrize(
    "patch",
    [
        {"cpu_threads": True},
        {"cpu_threads": "4"},
        {"max_pdf_pages": 0},
        {"max_pdf_pages": 10001},
        {"temperature": float("nan")},
        {"top_p": 1.1},
        {"chunk_tokens": 32, "chunk_overlap": 32},
        {"context_tokens": 4096, "max_output_tokens": 2048},
        {"database_url": "postgresql://private"},
        {"embedding_model": "other"},
    ],
)
def test_public_settings_reject_invalid_or_private_values(patch):
    with pytest.raises(ValidationError):
        PublicSettings.model_validate({**PublicSettings().model_dump(), **patch})


def test_read_and_save_global_settings_and_health(configured_client):
    client, state = configured_client
    before = client.get("/api/settings").json()
    assert before["revision"] == 0 and before["updated_at"] is None
    assert before["defaults"]["cpu_threads"] == 2
    assert set(before["values"]) == set(PublicSettings.model_fields)
    assert "database_url" not in before["values"]
    updated = {
        **before["values"],
        "temperature": 0.4,
        "max_pdf_pages": 1500,
        "max_upload_mb": 30,
        "retrieval_top_k": 8,
    }
    response = client.put("/api/settings", json={"revision": 0, "values": updated})
    assert response.status_code == 200
    data = response.json()
    assert data["values"] == updated and data["revision"] == 1 and data["updated_at"]
    assert data["defaults"] == before["defaults"]
    assert state.db.settings.max_pdf_pages == 1500
    assert state.embedder.settings.retrieval_top_k == 8
    assert state.llm.settings.temperature == 0.4
    assert client.get("/api/health").json()["limits"]["max_pdf_pages"] == 1500
    assert client.get("/api/settings").json() == data
    state.llm.models.assert_not_called()  # Offline tuning works without model changes.
    state.llm.selectable_model.assert_not_called()


def test_stale_browser_and_busy_inference_are_conflicts(configured_client):
    client, state = configured_client
    values = client.get("/api/settings").json()["values"]
    assert client.put("/api/settings", json={"revision": 0, "values": values}).status_code == 200
    stale = client.put("/api/settings", json={"revision": 0, "values": values})
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "settings_conflict"
    client.portal.call(state.inference_lock.acquire)
    try:
        busy = client.put("/api/settings", json={"revision": 1, "values": values})
        assert busy.status_code == 409
        assert busy.json()["detail"]["code"] == "runtime_busy"
    finally:
        client.portal.call(state.inference_lock.release)
    assert state.revision == 1


def test_endpoint_rejects_partial_values_extra_fields_and_bad_types(configured_client):
    client, _ = configured_client
    values = client.get("/api/settings").json()["values"]
    assert client.put("/api/settings", json={"revision": 0, "values": {}}).status_code == 422
    assert client.put("/api/settings", json={"revision": True, "values": values}).status_code == 422
    assert (
        client.put(
            "/api/settings",
            json={
                "revision": 0,
                "values": {**values, "cpu_threads": "2"},
            },
        ).status_code
        == 422
    )
    assert (
        client.put(
            "/api/settings",
            json={
                "revision": 0,
                "values": {**values, "database_url": "private"},
            },
        ).status_code
        == 422
    )


def test_model_must_be_locally_installed_and_offline_preserves_settings(configured_client):
    client, state = configured_client
    values = client.get("/api/settings").json()["values"]
    missing = client.put(
        "/api/settings",
        json={
            "revision": 0,
            "values": {**values, "ollama_model": "missing:1b"},
        },
    )
    assert missing.status_code == 422
    assert missing.json()["detail"][0]["loc"][-1] == "ollama_model"
    assert state.revision == 0
    state.llm.models.side_effect = httpx.ConnectError("private upstream address")
    state.llm.selectable_model.side_effect = httpx.ConnectError("private upstream address")
    assert client.get("/api/models").status_code == 503
    unavailable = client.put(
        "/api/settings",
        json={
            "revision": 0,
            "values": {**values, "ollama_model": "outro:1b"},
        },
    )
    assert unavailable.status_code == 503 and "private" not in unavailable.text
    assert state.revision == 0
    state.db.save_runtime_settings.assert_not_called()
    state.llm.models.side_effect = None
    state.llm.selectable_model.side_effect = lambda name: name == "outro:1b"
    installed = client.put(
        "/api/settings",
        json={
            "revision": 0,
            "values": {**values, "ollama_model": "outro:1b"},
        },
    )
    assert installed.status_code == 200
    assert state.settings.ollama_model == "outro:1b"


def test_failed_cpu_model_preparation_or_persistence_is_atomic(configured_client, monkeypatch):
    client, state = configured_client
    state.embedder.model = Mock()
    previous = state.embedder
    values = client.get("/api/settings").json()["values"]
    monkeypatch.setattr("rag.runtime.Embedder.load", Mock(side_effect=RuntimeError("private")))
    response = client.put(
        "/api/settings",
        json={
            "revision": 0,
            "values": {**values, "cpu_threads": 3},
        },
    )
    assert response.status_code == 503 and "private" not in response.text
    assert state.embedder is previous and state.settings.cpu_threads == 2 and state.revision == 0
    state.db.save_runtime_settings.assert_not_called()
    state.db.save_runtime_settings.side_effect = RuntimeError("private DB details")
    response = client.put(
        "/api/settings",
        json={
            "revision": 0,
            "values": {**values, "temperature": 1.0},
        },
    )
    assert response.status_code == 503 and "private" not in response.text
    assert state.settings.temperature == 0.15 and state.revision == 0


async def test_start_restores_saved_values_before_worker_and_keeps_environment_defaults(tmp_path):
    original = Settings(data_dir=tmp_path, temperature=0.25, cpu_threads=2)
    state = Runtime(original)
    saved_values = {**original.public().model_dump(), "temperature": 0.8, "cpu_threads": 3}
    state.db = SimpleNamespace(
        open=AsyncMock(),
        close=AsyncMock(),
        list_documents=AsyncMock(return_value=[]),
        load_runtime_settings=AsyncMock(
            return_value={
                "values": saved_values,
                "revision": 9,
                "updated_at": datetime.now(UTC),
            }
        ),
    )
    entered = asyncio.Event()

    async def worker():
        assert state.settings.cpu_threads == 3 and state.embedder.settings.cpu_threads == 3
        entered.set()
        await asyncio.Event().wait()

    state.worker = worker
    try:
        await state.start()
        await asyncio.wait_for(entered.wait(), timeout=2)
        assert state.settings.temperature == 0.8 and state.revision == 9
        assert state.defaults.temperature == 0.25 and state.defaults.cpu_threads == 2
    finally:
        await state.close()


async def test_cancelled_save_keeps_inference_lock_until_commit_and_snapshot_match():
    state = Runtime(Settings())
    entered, finish = asyncio.Event(), asyncio.Event()

    async def persist(revision, values):
        entered.set()
        await finish.wait()
        return {"revision": revision + 1, "values": values, "updated_at": datetime.now(UTC)}

    state.db.save_runtime_settings = persist
    values = PublicSettings.model_validate(
        {**state.settings.public().model_dump(), "temperature": 0.7}
    )
    operation = asyncio.create_task(state.update_settings(0, values))
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        operation.cancel()
        await asyncio.sleep(0)
        assert state.inference_lock.locked()
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await operation
        assert not state.inference_lock.locked()
        assert state.revision == 1 and state.settings.temperature == 0.7
    finally:
        finish.set()
        await state.llm.close()
