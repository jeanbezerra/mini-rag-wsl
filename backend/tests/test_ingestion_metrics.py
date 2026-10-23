import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from rag.config import Settings
from rag.runtime import Runtime


@pytest.mark.parametrize("success", [True, False])
async def test_worker_measures_success_and_failure_without_telemetry_changing_document_state(
    tmp_path, success
):
    runtime = Runtime(Settings(data_dir=tmp_path))
    runtime.settings.uploads_dir.mkdir()
    document = {"id": uuid4(), "name": "original.txt", "extension": ".txt"}
    (runtime.settings.uploads_dir / str(document["id"])).write_bytes(
        b"Texto original que sera ingerido." if success else b"\xff\x00"
    )
    called = asyncio.Event()
    claimed = False

    async def claim():
        nonlocal claimed
        if claimed:
            await asyncio.Event().wait()
        claimed = True
        return document

    async def record(metrics):
        called.set()
        raise RuntimeError("telemetry database unavailable")

    def embed(pages, measurements):
        measurements["embedding_ms"] = 2
        return [{"content": pages[0].text, "page": None, "token_count": 7, "embedding": "[0]"}]

    runtime.embedder = SimpleNamespace(model=object(), documents=Mock(side_effect=embed))
    runtime.db = SimpleNamespace(
        claim=claim,
        finish=AsyncMock(return_value=True),
        fail_document=AsyncMock(),
        record_ingestion_metrics=AsyncMock(side_effect=record),
    )
    task = asyncio.create_task(runtime.worker())
    try:
        await asyncio.wait_for(called.wait(), 2)
        metrics = runtime.db.record_ingestion_metrics.call_args.args[0]
        assert metrics["outcome"] == ("completed" if success else "error")
        assert metrics["extraction_ms"] >= 0 and metrics["duration_ms"] > 0
        assert "database_url" not in metrics["settings"]
        assert metrics["settings"]["embedding_model"] == runtime.settings.embedding_model
        assert metrics["chunks"] == (1 if success else None)
        if success:
            runtime.db.finish.assert_awaited_once()
            runtime.db.fail_document.assert_not_awaited()
            indexed = runtime.db.finish.call_args.args[2]
            assert indexed["token_counts"][7] == 1 and indexed["duplicate_chunks"] == 0
            assert indexed["total_pages"] is indexed["text_pages"] is None
        else:
            runtime.db.finish.assert_not_awaited()
            runtime.db.fail_document.assert_awaited_once()
            runtime.embedder.documents.assert_not_called()
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await runtime.llm.close()
