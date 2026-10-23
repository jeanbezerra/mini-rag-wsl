from datetime import UTC, datetime
from uuid import uuid4

from rag.analytics import indexing_summary, library_summary, measure_chunks, performance_summary


def measurements(tokens, **kwargs):
    counts = [0] * 129
    for token in tokens:
        counts[token] += 1
    return {"token_counts": counts, "duplicate_chunks": 0, **kwargs}


def document(name="manual.pdf", status="ready", metrics=None):
    return {
        "id": uuid4(),
        "name": name,
        "extension": ".pdf",
        "size_bytes": 100,
        "status": status,
        "chunk_count": 4,
        "indexing_metrics": metrics,
    }


def test_empty_and_legacy_measurements_stay_unknown():
    empty = library_summary([])
    assert empty["documents"]["total"] == empty["chunks"] == 0
    assert empty["indexing"]["tokens"]["p50"] is None
    assert empty["indexing"]["duplicate_chunks"] is None
    legacy = library_summary([document(), document(status="queued"), document(status="error")])
    assert legacy["indexing"]["legacy_documents"] == 1
    assert legacy["indexing"]["measured_documents"] == 0
    assert legacy["indexing"]["total_pages"] is None
    assert legacy["chunks"] == 4
    assert legacy["documents"]["total"] == 3
    assert legacy["formats"] == [{"extension": ".pdf", "documents": 3, "size_bytes": 300}]


def test_histogram_quantiles_are_weighted_by_actual_chunks_and_pages_only_measured_pdfs():
    first = measurements([10, 20, 30], total_pages=6, text_pages=4, duplicate_chunks=1)
    second = measurements([100], total_pages=None, text_pages=None)
    summary = library_summary([document(metrics=first), document(metrics=second), document()])
    indexing = summary["indexing"]
    assert indexing["tokens"] == {
        "measured_chunks": 4,
        "min": 10,
        "max": 100,
        "mean": 40,
        "p50": 25,
        "p95": 89.5,
    }
    assert indexing["measured_documents"] == 2 and indexing["legacy_documents"] == 1
    assert indexing["total_pages"] == 6 and indexing["empty_pages"] == 2
    assert indexing["duplicate_ratio"] == 0.25
    assert len(indexing["histogram"]) == 128
    assert indexing["histogram"][19] == {"tokens": 20, "count": 1}


def test_duplicate_measurement_counts_extra_exact_chunks_after_whitespace_normalization():
    metrics = measure_chunks(
        [
            {"content": "uma  linha\nnova", "token_count": 5},
            {"content": "uma linha nova", "token_count": 5},
            {"content": "uma Linha nova", "token_count": 5},
        ]
    )
    assert metrics["duplicate_chunks"] == 1
    assert indexing_summary([metrics])["duplicate_ratio"] == 0.333333
    # Repeated content in a different document is not an intra-document duplicate.
    assert (
        measure_chunks([{"content": "uma linha nova", "token_count": 5}])["duplicate_chunks"] == 0
    )


def chat(model="local", outcome="completed", duration=100, speed=20):
    return {
        "id": uuid4(),
        "created_at": datetime.now(UTC),
        "model": model,
        "outcome": outcome,
        "duration_ms": duration,
        "search_ms": duration / 10,
        "first_token_ms": 30,
        "output_tokens": 5,
        "tokens_per_second": speed,
    }


def test_performance_uses_completed_samples_and_preserves_model_filter_scope():
    items = [
        chat(duration=100),
        chat(duration=300, speed=None),
        chat("other", duration=900),
        chat(outcome="error", duration=10000),
        chat(outcome="no_sources", duration=10000),
    ]
    summary = performance_summary(items, [], "local")
    assert summary["models"] == ["local", "other"]
    assert summary["chat"]["samples"] == 4
    assert summary["chat"]["completed"] == 2
    assert summary["chat"]["latency_ms"] == {"p50": 200, "p95": 290}
    assert summary["chat"]["tokens_per_second"] == {"p50": 20, "p95": 20}
    assert summary["chat"]["output_tokens"] == 10
    assert len(summary["recent_chat"]) == 4
    assert summary["ingestion"]["duration_ms"] == {"p50": None, "p95": None}
    assert summary["window"]["limit"] == 500
