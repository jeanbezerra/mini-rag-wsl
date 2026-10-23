"""Small, content-free measurements. Missing historical measurements stay unknown."""

import hashlib
import math
from collections import Counter

METRICS_LIMIT = 500


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = (len(ordered) - 1) * fraction
    lower, upper = math.floor(rank), math.ceil(rank)
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * (rank - lower), 3)


def distribution(values: list[float]) -> dict:
    return {"p50": percentile(values, 0.5), "p95": percentile(values, 0.95)}


def histogram_summary(counts: list[int]) -> dict:
    size = sum(counts)

    def item_at(rank: int) -> int:
        accumulated = 0
        for tokens, count in enumerate(counts):
            accumulated += count
            if accumulated > rank:
                return tokens
        raise ValueError("Empty token histogram")

    def quantile(fraction: float) -> float | None:
        if not size:
            return None
        rank = (size - 1) * fraction
        lower, upper = item_at(math.floor(rank)), item_at(math.ceil(rank))
        return round(lower + (upper - lower) * (rank - math.floor(rank)), 3)

    populated = [tokens for tokens, count in enumerate(counts) if count]
    return {
        "tokens": {
            "measured_chunks": size,
            "min": min(populated) if populated else None,
            "max": max(populated) if populated else None,
            "mean": round(sum(i * n for i, n in enumerate(counts)) / size, 3) if size else None,
            "p50": quantile(0.5),
            "p95": quantile(0.95),
        },
        "histogram": [{"tokens": i, "count": counts[i]} for i in range(1, 129)],
    }


def measure_chunks(chunks: list[dict]) -> dict:
    counts = [0] * 129
    fingerprints = Counter()
    for chunk in chunks:
        counts[chunk["token_count"]] += 1
        # Exact equality after whitespace normalization, within this document only.
        content = " ".join(chunk["content"].split()).encode("utf-8")
        fingerprints[hashlib.sha256(content).digest()] += 1
    return {
        "token_counts": counts,
        "duplicate_chunks": sum(count - 1 for count in fingerprints.values()),
    }


def indexing_summary(metrics: list[dict]) -> dict:
    counts = [0] * 129
    for item in metrics:
        for index, value in enumerate(item["token_counts"]):
            counts[index] += value
    size = sum(counts)
    duplicates = sum(item["duplicate_chunks"] for item in metrics) if metrics else None
    return {
        **histogram_summary(counts),
        "duplicate_chunks": duplicates,
        "duplicate_ratio": round(duplicates / size, 6) if size else None,
    }


def document_row(row: dict) -> dict:
    metrics = row.get("indexing_metrics") or {}
    return {
        **{key: value for key, value in row.items() if key != "indexing_metrics"},
        "ingestion_ms": metrics.get("duration_ms"),
        "extracted_characters": metrics.get("extracted_characters"),
        "total_pages": metrics.get("total_pages"),
        "text_pages": metrics.get("text_pages"),
    }


def library_summary(rows: list[dict]) -> dict:
    statuses = Counter(row["status"] for row in rows)
    ready = [row for row in rows if row["status"] == "ready"]
    measured = [row["indexing_metrics"] for row in ready if row["indexing_metrics"]]
    pdfs = [item for item in measured if item.get("total_pages") is not None]
    pages = sum(item["total_pages"] for item in pdfs) if pdfs else None
    text_pages = sum(item["text_pages"] for item in pdfs) if pdfs else None
    formats = {}
    for row in rows:
        entry = formats.setdefault(
            row["extension"], {"extension": row["extension"], "documents": 0, "size_bytes": 0}
        )
        entry["documents"] += 1
        entry["size_bytes"] += row["size_bytes"]
    return {
        "documents": {
            "total": len(rows),
            **{key: statuses[key] for key in ("queued", "processing", "ready", "error")},
        },
        "storage_bytes": sum(row["size_bytes"] for row in rows),
        "chunks": sum(row["chunk_count"] for row in ready),
        "formats": sorted(
            formats.values(), key=lambda item: (-item["documents"], item["extension"])
        ),
        "largest_documents": [
            {key: row[key] for key in ("id", "name", "chunk_count")}
            for row in sorted(ready, key=lambda item: (-item["chunk_count"], str(item["id"])))[:8]
        ],
        "indexing": {
            "measured_documents": len(measured),
            "legacy_documents": len(ready) - len(measured),
            "total_pages": pages,
            "text_pages": text_pages,
            "empty_pages": pages - text_pages if pages is not None else None,
            **indexing_summary(measured),
        },
    }


def performance_summary(chats: list[dict], ingestions: list[dict], model: str | None) -> dict:
    # Filter inside the retained global window; no invented lifetime statistics.
    models = sorted({item["model"] for item in chats})
    chats = [item for item in chats if not model or item["model"] == model]
    completed = [item for item in chats if item["outcome"] == "completed"]
    ingested = [item for item in ingestions if item["outcome"] == "completed"]

    def values(items: list[dict], key: str) -> list[float]:
        return [item[key] for item in items if item[key] is not None]

    dates = [item["created_at"] for item in [*chats, *ingestions]]
    return {
        "window": {
            "limit": METRICS_LIMIT,
            "from": min(dates) if dates else None,
            "to": max(dates) if dates else None,
        },
        "models": models,
        "chat": {
            "samples": len(chats),
            **{
                key: sum(item["outcome"] == key for item in chats)
                for key in ("completed", "no_sources", "error", "cancelled")
            },
            "latency_ms": distribution(values(completed, "duration_ms")),
            "search_ms": distribution(values(completed, "search_ms")),
            "first_token_ms": distribution(values(completed, "first_token_ms")),
            "tokens_per_second": distribution(values(completed, "tokens_per_second")),
            "output_tokens": sum(values(completed, "output_tokens")),
        },
        "ingestion": {
            "samples": len(ingestions),
            "completed": len(ingested),
            "error": len(ingestions) - len(ingested),
            "duration_ms": distribution(values(ingested, "duration_ms")),
            "chunks_per_second": distribution(values(ingested, "chunks_per_second")),
        },
        "recent_chat": [
            {
                key: item[key]
                for key in (
                    "id",
                    "created_at",
                    "model",
                    "outcome",
                    "duration_ms",
                    "search_ms",
                    "first_token_ms",
                    "output_tokens",
                    "tokens_per_second",
                )
            }
            for item in chats
        ],
        "recent_ingestion": [
            {
                key: item[key]
                for key in (
                    "id",
                    "document_name",
                    "created_at",
                    "outcome",
                    "duration_ms",
                    "chunks",
                    "extraction_ms",
                    "embedding_ms",
                )
            }
            for item in ingestions
        ],
    }
