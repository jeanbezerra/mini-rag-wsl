"""Opt-in tests against an isolated PostgreSQL 18 + pgvector, never production data."""

import asyncio
import os
from uuid import uuid4

import psycopg
import pytest

from rag.analytics import measure_chunks
from rag.config import Settings
from rag.db import Database
from rag.embedding import vector_literal
from rag.migrate import migrate
from rag.runtime import Runtime

APP_URL = os.getenv("TEST_DATABASE_URL")
MIGRATION_URL = os.getenv("TEST_MIGRATION_DATABASE_URL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not APP_URL or not MIGRATION_URL,
        reason="Set TEST_DATABASE_URL and TEST_MIGRATION_DATABASE_URL",
    ),
]


@pytest.fixture(scope="module", autouse=True)
def initialize_schema():
    if MIGRATION_URL:
        settings = Settings(database_url=MIGRATION_URL)
        asyncio.run(migrate(settings))
        asyncio.run(migrate(settings))  # Both first installation and repeat runs must work.


async def test_queue_recovery_hybrid_search_dedupe_and_runtime_permissions():
    settings = Settings(database_url=APP_URL)
    db = Database(settings)
    await db.open()
    document_id = uuid4()
    duplicate_id = uuid4()
    value = vector_literal([1.0] + [0.0] * 383)
    try:
        document = {
            "id": document_id,
            "name": "manual-teste.txt",
            "extension": ".txt",
            "sha256": document_id.hex * 2,
            "size_bytes": 100,
        }
        row = await db.add_document(document)
        assert row["status"] == "queued"
        with pytest.raises(psycopg.errors.UniqueViolation):
            await db.add_document({**document, "id": duplicate_id})
        claimed = await db.claim()
        assert claimed["id"] == document_id
        # A dropped dedicated advisory-lock session is reacquired without restarting API.
        await db.worker_connection.close()
        claimed = await db.claim()
        assert claimed["id"] == document_id
        # Reopening releases session lock and recovers interrupted processing work.
        await db.close()
        db = Database(settings)
        await db.open()
        claimed = await db.claim()
        assert claimed["id"] == document_id
        chunk_id = uuid4()
        await db.finish(
            document_id,
            [
                {
                    "id": chunk_id,
                    "document_id": document_id,
                    "ordinal": 0,
                    "page": 3,
                    "content": "Reembolso das despesas de viagens corporativas.",
                    "embedding": value,
                }
            ],
        )
        results = await db.search("reembolso de viagem", value, [document_id], 6)
        assert results and results[0]["id"] == chunk_id and results[0]["score"] > 0
        orthogonal = vector_literal([0.0, 1.0] + [0.0] * 382)
        assert await db.search("reembolso", orthogonal, [document_id], 6)  # FTS-only match.
        assert await db.search("xyz1234", value, [document_id], 6)  # Semantic-only match.
        assert await db.search("xyz1234", orthogonal, [document_id], 6) == []
        assert await db.search("reembolso", value, [], 6) == []
        # App must have DML access, but no permission to modify its schema.
        async with db.pool.connection() as conn:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                await conn.execute("CREATE TABLE rag.permission_probe (id integer)")
        await db.delete_document(document_id)
        assert await db.search("reembolso", value, [document_id], 6) == []
    finally:
        await db.delete_document(document_id)
        await db.delete_document(duplicate_id)
        await db.close()


async def test_second_worker_rejected():
    first, second = (
        Database(Settings(database_url=APP_URL)),
        Database(Settings(database_url=APP_URL)),
    )
    await first.open()
    try:
        with pytest.raises(RuntimeError, match="única"):
            await second.open()
    finally:
        await first.close()
        await second.close()


async def test_runtime_settings_cas_restart_and_minimal_permissions(tmp_path):
    db = Database(Settings(database_url=APP_URL))
    await db.open()
    original = await db.load_runtime_settings()
    values = Settings().public().model_dump()
    try:
        first = await db.save_runtime_settings(
            original["revision"], {**values, "max_pdf_pages": 1750, "temperature": 0.4}
        )
        assert first["revision"] == original["revision"] + 1 and first["updated_at"]
        # Two simultaneous browsers holding the same revision: exactly one wins.
        competing = await asyncio.gather(
            *(
                db.save_runtime_settings(
                    first["revision"], {**first["values"], "temperature": temperature}
                )
                for temperature in (0.6, 0.8)
            )
        )
        assert sum(row is not None for row in competing) == 1
        winner = next(row for row in competing if row is not None)
        assert await db.load_runtime_settings() == winner
        async with db.pool.connection() as conn:
            for command in (
                "INSERT INTO rag.runtime_settings (singleton) VALUES (true)",
                "DELETE FROM rag.runtime_settings WHERE singleton=true",
                "UPDATE rag.runtime_settings SET singleton=false WHERE singleton=true",
            ):
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    async with conn.transaction():
                        await conn.execute(command)
        await db.close()
        # A new application process restores the database values over environment
        # defaults before spawning the ingestion worker, without changing the index.
        runtime = Runtime(Settings(database_url=APP_URL, data_dir=tmp_path, temperature=0.1))

        async def no_worker():
            return None

        runtime.worker = no_worker
        try:
            await runtime.start()
            assert runtime.settings.max_pdf_pages == 1750
            assert runtime.settings.temperature == winner["values"]["temperature"]
            assert runtime.defaults.temperature == 0.1
            assert runtime.revision == winner["revision"]
        finally:
            await runtime.close()
    finally:
        # The disposable test database remains usable by following integration tests.
        await db.close()
        db = Database(Settings(database_url=APP_URL))
        await db.open()
        current = await db.load_runtime_settings()
        await db.save_runtime_settings(current["revision"], original["values"])
        await db.close()


async def test_library_legacy_detail_pagination_and_atomic_reindex_races():
    db = Database(Settings(database_url=APP_URL))
    await db.open()
    first, second = uuid4(), uuid4()
    prefix = "library-" + uuid4().hex
    value = vector_literal([1.0] + [0.0] * 383)

    def chunk(identifier, ordinal=0, token_count=None):
        return {
            "id": uuid4(),
            "document_id": identifier,
            "ordinal": ordinal,
            "content": "Conteúdo vetorial de teste",
            "page": ordinal + 1,
            "embedding": value,
            "token_count": token_count,
        }

    try:
        for identifier, suffix in ((first, " A_100%"), (second, " B")):
            await db.add_document(
                {
                    "id": identifier,
                    "name": prefix + suffix,
                    "extension": ".pdf",
                    "sha256": identifier.hex * 2,
                    "size_bytes": 100,
                }
            )
            assert (await db.claim())["id"] == identifier
            chunks = (
                [chunk(identifier)]
                if identifier == first
                else [chunk(identifier, i, 17) for i in range(2)]
            )
            metadata = None
            if identifier == second:
                metadata = {
                    **measure_chunks(chunks),
                    "total_pages": 3,
                    "text_pages": 2,
                    "extracted_characters": 100,
                    "duration_ms": 50,
                    "extraction_ms": 10,
                    "embedding_ms": 30,
                    "finished_at": "2026-10-22T12:00:00+00:00",
                    "settings": {"chunk_tokens": 110, "cpu_threads": 4},
                }
            await db.finish(identifier, chunks, metadata)
        literal = await db.library_documents("A_100%", "ready", "name", 1, 20)
        assert literal["total"] == 1 and literal["documents"][0]["id"] == first
        paged = await db.library_documents(prefix, "ready", "name", 2, 1)
        assert paged["total"] == 2 and paged["documents"][0]["id"] == second
        legacy = await db.library_document(first, 1, 5)
        assert legacy["ingestion"] is None
        assert legacy["chunks"]["items"][0]["token_count"] is None
        measured = await db.library_document(second, 2, 1)
        assert measured["indexing"]["tokens"]["measured_chunks"] == 2
        assert measured["indexing"]["duplicate_ratio"] == 0.5
        assert measured["chunks"]["items"][0]["ordinal"] == 1
        assert measured["document"]["total_pages"] == 3
        assert measured["ingestion"]["settings"]["chunk_tokens"] == 110
        summary = await db.library_summary()
        assert summary["indexing"]["legacy_documents"] >= 1
        assert summary["indexing"]["tokens"]["measured_chunks"] >= 2
        # Concurrent confirmations enqueue the file once, atomically clearing all
        # vectors and obsolete measurements while preserving its document identity.
        attempts = await asyncio.gather(db.reindex_document(second), db.reindex_document(second))
        assert sum(item is not None for item in attempts) == 1
        pending = await db.library_document(second, 1, 5)
        assert pending["document"]["status"] == "queued"
        assert pending["document"]["chunk_count"] == pending["chunks"]["total"] == 0
        assert pending["ingestion"] is None
        assert (await db.claim())["id"] == second
        assert await db.reindex_document(second) is None
        await db.fail_document(second, "Nova ingestão falhou")
        assert await db.search("vetorial", value, [second], 6) == []
        assert await db.reindex_document(second) is None
        await db.retry_document(second)
        assert (await db.claim())["id"] == second
        await db.finish(second, [chunk(second)])
        # Delete and reindex acquire the same parent-row lock first. Either order
        # leaves no orphan vectors and cannot revive a deleted file.
        await asyncio.gather(db.reindex_document(second), db.delete_document(second))
        assert await db.library_document(second, 1, 5) is None
    finally:
        await db.delete_document(first)
        await db.delete_document(second)
        await db.close()


async def test_metrics_retention_is_global_and_runtime_cannot_update_measurements():
    db = Database(Settings(database_url=APP_URL))
    await db.open()
    marker = "metrics-test-" + uuid4().hex
    try:
        async with db.pool.connection() as conn:
            # Seed a bounded disposable workload without 1,000 network round trips.
            await conn.execute(
                "INSERT INTO rag.chat_metrics (id,model,outcome,duration_ms,search_ms,settings) "
                "SELECT uuidv7(),%s,'completed',n,n / 2.0,'{}'::jsonb "
                "FROM generate_series(1,502) AS n",
                (marker,),
            )
            await conn.execute(
                "INSERT INTO rag.ingestion_metrics (id,document_name,outcome,duration_ms,settings) "
                "SELECT uuidv7(),%s,'error',n,'{}'::jsonb FROM generate_series(1,502) AS n",
                (marker,),
            )
        await db.record_chat_metrics(
            {
                "id": uuid4(),
                "model": marker,
                "outcome": "completed",
                "duration_ms": 40,
                "wait_ms": 1,
                "search_ms": 2,
                "embedding_ms": 1,
                "first_token_ms": 10,
                "output_tokens": 10,
                "tokens_per_second": 5,
                "source_count": 1,
                "settings": {},
            }
        )
        await db.record_ingestion_metrics(
            {
                "id": uuid4(),
                "document_id": None,
                "document_name": marker,
                "outcome": "error",
                "duration_ms": 50,
                "extraction_ms": None,
                "embedding_ms": None,
                "chunks": None,
                "chunks_per_second": None,
                "settings": {},
            }
        )
        summary = await db.library_performance(marker)
        assert summary["chat"]["samples"] == len(summary["recent_chat"]) == 500
        assert summary["ingestion"]["samples"] == len(summary["recent_ingestion"]) == 500
        assert summary["chat"]["tokens_per_second"] == {"p50": 5, "p95": 5}
        assert summary["ingestion"]["duration_ms"] == {"p50": None, "p95": None}
        assert (await db.library_performance("unknown"))["chat"]["samples"] == 0
        async with db.pool.connection() as conn:
            for table in ("chat_metrics", "ingestion_metrics"):
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    async with conn.transaction():
                        await conn.execute(f"UPDATE rag.{table} SET duration_ms=1")
    finally:
        async with db.pool.connection() as conn:
            await conn.execute("DELETE FROM rag.chat_metrics WHERE model=%s", (marker,))
            await conn.execute(
                "DELETE FROM rag.ingestion_metrics WHERE document_name=%s", (marker,)
            )
        await db.close()
