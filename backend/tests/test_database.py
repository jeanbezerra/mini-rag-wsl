"""Opt-in tests against an isolated PostgreSQL 18 + pgvector, never production data."""

import asyncio
import os
from uuid import uuid4

import psycopg
import pytest

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
