"""Run once with DATABASE_URL belonging to rag_migrator, before starting the API."""

import asyncio
import sys
from pathlib import Path

import psycopg

from rag.config import Settings


async def migrate(settings: Settings | None = None) -> None:
    settings = settings or Settings()
    async with await psycopg.AsyncConnection.connect(settings.database_url) as conn:
        await conn.execute("SET lock_timeout = '10s'")
        await conn.execute("SET statement_timeout = '60s'")
        await conn.execute("SELECT pg_advisory_xact_lock(913605, 2)")
        version = (await (await conn.execute("SHOW server_version_num")).fetchone())[0]
        if not 180000 <= int(version) < 190000:
            raise RuntimeError("PostgreSQL 18.x obrigatório.")
        await conn.execute(Path(__file__).with_name("schema.sql").read_text("utf-8"))
        existing = await (
            await conn.execute("SELECT value FROM rag.settings WHERE key='embedding_model'")
        ).fetchone()
        if existing and existing[0] != settings.embedding_model:
            raise RuntimeError("EMBEDDING_MODEL alterado; reindexação em banco novo necessária.")
        await conn.execute(
            "INSERT INTO rag.settings (key,value) VALUES ('embedding_model',%s) "
            "ON CONFLICT DO NOTHING",
            (settings.embedding_model,),
        )
    print("Schema RAG atualizado para PostgreSQL 18.")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(migrate())
