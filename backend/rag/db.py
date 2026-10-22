from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from rag.config import Settings

DOCUMENT_COLUMNS = "id, name, size_bytes, status, chunk_count, created_at, error"


class Database:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.pool = AsyncConnectionPool(
            settings.database_url,
            min_size=1,
            max_size=5,
            open=False,
            kwargs={"row_factory": dict_row, "connect_timeout": 10},
            timeout=10,
        )
        self.worker_connection: psycopg.AsyncConnection | None = None

    async def open(self) -> None:
        await self.pool.open(wait=True)
        async with self.pool.connection() as conn:
            result = await (await conn.execute("SHOW server_version_num")).fetchone()
            version = int(result["server_version_num"])
            if not 180000 <= version < 190000:
                raise RuntimeError("Este projeto exige PostgreSQL 18.x.")
            existing = await (
                await conn.execute("SELECT value FROM rag.settings WHERE key = 'embedding_model'")
            ).fetchone()
            if not existing or existing["value"] != self.settings.embedding_model:
                raise RuntimeError(
                    "EMBEDDING_MODEL difere do índice existente; use um banco novo para reindexar."
                )
        await self.acquire_worker_lock()

    async def acquire_worker_lock(self) -> None:
        # Session lock enforces one embedded worker, including after database restarts.
        if self.worker_connection:
            await self.worker_connection.close()
            self.worker_connection = None
        self.worker_connection = await psycopg.AsyncConnection.connect(
            self.settings.database_url,
            autocommit=True,
            connect_timeout=10,
        )
        acquired = await (
            await self.worker_connection.execute("SELECT pg_try_advisory_lock(913605, 1)")
        ).fetchone()
        if not acquired[0]:
            await self.worker_connection.close()
            self.worker_connection = None
            raise RuntimeError("Execute uma única instância/worker da API para este banco.")
        async with self.pool.connection() as conn:
            await conn.execute(
                "UPDATE rag.documents SET status='queued', updated_at=now(), error=NULL "
                "WHERE status='processing'"
            )

    async def close(self) -> None:
        if self.worker_connection:
            await self.worker_connection.close()
            self.worker_connection = None
        await self.pool.close()

    async def health(self) -> dict:
        async with self.pool.connection() as conn:
            row = await (await conn.execute("SHOW server_version")).fetchone()
            return {"status": "ok", "version": row["server_version"]}

    async def list_documents(self) -> list[dict]:
        async with self.pool.connection() as conn:
            return await (
                await conn.execute(
                    f"SELECT {DOCUMENT_COLUMNS} FROM rag.documents ORDER BY created_at DESC, id"
                )
            ).fetchall()

    async def add_document(self, document: dict) -> dict:
        async with self.pool.connection() as conn:
            # Serialize quota checks; uniqueness is still enforced by the database.
            await conn.execute("SELECT pg_advisory_xact_lock(913605, 3)")
            total = await (await conn.execute("SELECT count(*) AS n FROM rag.documents")).fetchone()
            if total["n"] >= self.settings.max_documents:
                raise OverflowError(
                    "Limite de documentos atingido. Exclua arquivos antes de enviar."
                )
            return await (
                await conn.execute(
                    "INSERT INTO rag.documents (id, name, extension, sha256, size_bytes) "
                    f"VALUES (%(id)s, %(name)s, %(extension)s, %(sha256)s, %(size_bytes)s) "
                    f"RETURNING {DOCUMENT_COLUMNS}",
                    document,
                )
            ).fetchone()

    async def delete_document(self, document_id: UUID) -> bool:
        async with self.pool.connection() as conn:
            result = await conn.execute("DELETE FROM rag.documents WHERE id=%s", (document_id,))
            return result.rowcount > 0

    async def retry_document(self, document_id: UUID) -> dict | None:
        async with self.pool.connection() as conn:
            return await (
                await conn.execute(
                    "UPDATE rag.documents SET status='queued', error=NULL, updated_at=now() "
                    f"WHERE id=%s AND status='error' RETURNING {DOCUMENT_COLUMNS}",
                    (document_id,),
                )
            ).fetchone()

    async def claim(self) -> dict | None:
        # Reconnect and requeue only after reacquiring the exclusive worker lease.
        try:
            if self.worker_connection is None:
                raise psycopg.OperationalError("Worker lease unavailable")
            await self.worker_connection.execute("SELECT 1")
        except (psycopg.OperationalError, psycopg.InterfaceError):
            await self.acquire_worker_lock()
        async with self.pool.connection() as conn:
            return await (
                await conn.execute(
                    "UPDATE rag.documents SET status='processing', updated_at=now(), error=NULL "
                    "WHERE id=(SELECT id FROM rag.documents WHERE status='queued' "
                    "ORDER BY created_at,id FOR UPDATE SKIP LOCKED LIMIT 1) "
                    "RETURNING id, name, extension"
                )
            ).fetchone()

    async def fail_document(self, document_id: UUID, message: str) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                "UPDATE rag.documents SET status='error', error=%s, updated_at=now() "
                "WHERE id=%s AND status='processing'",
                (message[:500], document_id),
            )

    async def finish(self, document_id: UUID, chunks: list[dict]) -> None:
        async with self.pool.connection() as conn:
            parent = await (
                await conn.execute(
                    "SELECT id FROM rag.documents WHERE id=%s AND status='processing' FOR UPDATE",
                    (document_id,),
                )
            ).fetchone()
            if parent is None:  # Deleted while extraction was running.
                return
            await conn.execute("DELETE FROM rag.chunks WHERE document_id=%s", (document_id,))
            async with conn.cursor() as cur:
                await cur.executemany(
                    "INSERT INTO rag.chunks "
                    "(id, document_id, ordinal, page, content, embedding) "
                    "VALUES (%(id)s,%(document_id)s,%(ordinal)s,%(page)s,%(content)s,"
                    "%(embedding)s::public.vector)",
                    chunks,
                )
            await conn.execute(
                "UPDATE rag.documents SET status='ready', chunk_count=%s, error=NULL, "
                "updated_at=now() WHERE id=%s",
                (len(chunks), document_id),
            )

    async def search(
        self, query: str, embedding: str, ids: list[UUID] | None, limit: int
    ) -> list[dict]:
        params: dict[str, Any] = {
            "embedding": embedding,
            "query": query,
            "ids": ids,
            "limit": limit,
            "similarity": self.settings.min_similarity,
        }
        # RRF balances semantic and Portuguese lexical results without mixing score scales.
        sql = """
        WITH semantic_top AS (
            SELECT c.id, c.embedding <=> %(embedding)s::public.vector AS distance
            FROM rag.chunks c JOIN rag.documents d ON d.id=c.document_id
            WHERE d.status='ready'
              AND (%(ids)s::uuid[] IS NULL OR c.document_id=ANY(%(ids)s::uuid[]))
              AND c.embedding <=> %(embedding)s::public.vector <= 1.0 - %(similarity)s
            ORDER BY distance,c.id LIMIT 30
        ), semantic AS (
            SELECT id, row_number() OVER (ORDER BY distance,id) AS rank
            FROM semantic_top
        ), lexical_top AS (
            SELECT c.id, ts_rank_cd(c.search_vector,
                websearch_to_tsquery('portuguese', %(query)s)) AS lexical
            FROM rag.chunks c JOIN rag.documents d ON d.id=c.document_id
            WHERE d.status='ready'
              AND (%(ids)s::uuid[] IS NULL OR c.document_id=ANY(%(ids)s::uuid[]))
              AND c.search_vector @@ websearch_to_tsquery('portuguese', %(query)s)
            ORDER BY lexical DESC,c.id LIMIT 30
        ), lexical AS (
            SELECT id, row_number() OVER (ORDER BY lexical DESC,id) AS rank
            FROM lexical_top
        ), fused AS (
            SELECT coalesce(s.id,l.id) AS id,
                coalesce(1.0/(60+s.rank),0) + coalesce(1.0/(60+l.rank),0) AS score
            FROM semantic s FULL OUTER JOIN lexical l ON s.id=l.id
        )
        SELECT c.id,c.document_id,d.name,c.page,c.content,f.score::float8 AS score
        FROM fused f JOIN rag.chunks c ON c.id=f.id JOIN rag.documents d ON d.id=c.document_id
        ORDER BY f.score DESC,c.id LIMIT %(limit)s
        """
        async with self.pool.connection() as conn:
            return await (await conn.execute(sql, params)).fetchall()
