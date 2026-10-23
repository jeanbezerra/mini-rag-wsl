from time import perf_counter
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from rag.analytics import (
    METRICS_LIMIT,
    document_row,
    indexing_summary,
    library_summary,
    performance_summary,
)
from rag.config import Settings

DOCUMENT_COLUMNS = "id, name, size_bytes, status, chunk_count, created_at, error"
LIBRARY_COLUMNS = DOCUMENT_COLUMNS + ", extension, updated_at, indexing_metrics"


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

    async def load_runtime_settings(self) -> dict:
        async with self.pool.connection() as conn:
            row = await (
                await conn.execute(
                    "SELECT config_values AS values, revision, updated_at "
                    "FROM rag.runtime_settings "
                    "WHERE singleton=true"
                )
            ).fetchone()
            if row is None:
                raise RuntimeError("Configurações ausentes. Execute a migração do banco.")
            return row

    async def save_runtime_settings(self, revision: int, values: dict) -> dict | None:
        # Compare-and-set is atomic. No stale browser can overwrite a newer revision.
        async with self.pool.connection() as conn:
            return await (
                await conn.execute(
                    "UPDATE rag.runtime_settings SET config_values=%s, revision=revision+1, "
                    "updated_at=now() WHERE singleton=true AND revision=%s "
                    "RETURNING config_values AS values, revision, updated_at",
                    (Jsonb(values), revision),
                )
            ).fetchone()

    async def list_documents(self) -> list[dict]:
        async with self.pool.connection() as conn:
            return await (
                await conn.execute(
                    f"SELECT {DOCUMENT_COLUMNS} FROM rag.documents ORDER BY created_at DESC, id"
                )
            ).fetchall()

    async def library_summary(self) -> dict:
        async with self.pool.connection() as conn:
            rows = await (
                await conn.execute(
                    "SELECT id,name,extension,size_bytes,status,chunk_count,indexing_metrics "
                    "FROM rag.documents"
                )
            ).fetchall()
        return library_summary(rows)

    async def library_documents(
        self, query: str, status: str | None, sort: str, page: int, page_size: int
    ) -> dict:
        orders = {
            "newest": "created_at DESC,id",
            "name": "lower(name),id",
            "size": "size_bytes DESC,id",
            "chunks": "chunk_count DESC,id",
        }
        order = orders[sort]  # Validated enum, never SQL supplied by a caller.
        query = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        where = "WHERE name ILIKE %s AND (%s::text IS NULL OR status=%s)"
        params = (f"%{query}%", status, status)
        async with self.pool.connection() as conn:
            total = await (
                await conn.execute(f"SELECT count(*) AS n FROM rag.documents {where}", params)
            ).fetchone()
            rows = await (
                await conn.execute(
                    f"SELECT {LIBRARY_COLUMNS} FROM rag.documents {where} "
                    f"ORDER BY {order} LIMIT %s OFFSET %s",
                    (*params, page_size, (page - 1) * page_size),
                )
            ).fetchall()
        return {
            "documents": [document_row(row) for row in rows],
            "total": total["n"],
            "page": page,
            "page_size": page_size,
        }

    async def library_document(self, document_id: UUID, page: int, page_size: int) -> dict | None:
        async with self.pool.connection() as conn, conn.transaction():
            # The document header and sampled chunks describe one consistent snapshot
            # even if another browser reindexes or deletes this file simultaneously.
            await conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            row = await (
                await conn.execute(
                    f"SELECT {LIBRARY_COLUMNS} FROM rag.documents WHERE id=%s", (document_id,)
                )
            ).fetchone()
            if row is None:
                return None
            chunks = await (
                await conn.execute(
                    "SELECT id,ordinal,page,content,token_count,length(content) AS char_count "
                    "FROM rag.chunks WHERE document_id=%s ORDER BY ordinal,id LIMIT %s OFFSET %s",
                    (document_id, page_size, (page - 1) * page_size),
                )
            ).fetchall()
            total = await (
                await conn.execute(
                    "SELECT count(*) AS n FROM rag.chunks WHERE document_id=%s", (document_id,)
                )
            ).fetchone()
        metrics = row["indexing_metrics"]
        ingestion = None
        if metrics:
            ingestion = {
                key: metrics[key]
                for key in (
                    "duration_ms",
                    "extraction_ms",
                    "embedding_ms",
                    "finished_at",
                    "settings",
                )
            }
        return {
            "document": document_row(row),
            "indexing": indexing_summary([metrics] if metrics else []),
            "ingestion": ingestion,
            "chunks": {"items": chunks, "total": total["n"], "page": page, "page_size": page_size},
        }

    async def reindex_document(self, document_id: UUID) -> dict | None:
        async with self.pool.connection() as conn:
            row = await (
                await conn.execute(
                    "SELECT status FROM rag.documents WHERE id=%s FOR UPDATE", (document_id,)
                )
            ).fetchone()
            if row is None or row["status"] != "ready":
                return None
            # Replace only this document. Its original file is left untouched.
            # Erasing the old vectors prevents stale search results after a failed retry.
            await conn.execute("DELETE FROM rag.chunks WHERE document_id=%s", (document_id,))
            return await (
                await conn.execute(
                    "UPDATE rag.documents SET status='queued',chunk_count=0,error=NULL,"
                    "indexing_metrics=NULL,updated_at=now() WHERE id=%s "
                    f"RETURNING {DOCUMENT_COLUMNS}",
                    (document_id,),
                )
            ).fetchone()

    async def record_chat_metrics(self, metrics: dict) -> None:
        async with self.pool.connection() as conn:
            await conn.execute("SELECT pg_advisory_xact_lock(913605, 4)")
            await conn.execute(
                "INSERT INTO rag.chat_metrics (id,model,outcome,duration_ms,wait_ms,search_ms,"
                "embedding_ms,first_token_ms,output_tokens,tokens_per_second,source_count,"
                "settings) "
                "VALUES (%(id)s,%(model)s,%(outcome)s,%(duration_ms)s,%(wait_ms)s,%(search_ms)s,"
                "%(embedding_ms)s,%(first_token_ms)s,%(output_tokens)s,%(tokens_per_second)s,"
                "%(source_count)s,%(settings)s)",
                {**metrics, "settings": Jsonb(metrics["settings"])},
            )
            await conn.execute(
                "DELETE FROM rag.chat_metrics WHERE id IN "
                "(SELECT id FROM rag.chat_metrics ORDER BY created_at DESC,id DESC OFFSET %s)",
                (METRICS_LIMIT,),
            )

    async def record_ingestion_metrics(self, metrics: dict) -> None:
        async with self.pool.connection() as conn:
            await conn.execute("SELECT pg_advisory_xact_lock(913605, 4)")
            await conn.execute(
                "INSERT INTO rag.ingestion_metrics (id,document_id,document_name,outcome,"
                "duration_ms,extraction_ms,embedding_ms,chunks,chunks_per_second,settings) "
                "VALUES (%(id)s,%(document_id)s,%(document_name)s,%(outcome)s,%(duration_ms)s,"
                "%(extraction_ms)s,%(embedding_ms)s,%(chunks)s,%(chunks_per_second)s,%(settings)s)",
                {**metrics, "settings": Jsonb(metrics["settings"])},
            )
            await conn.execute(
                "DELETE FROM rag.ingestion_metrics WHERE id IN "
                "(SELECT id FROM rag.ingestion_metrics ORDER BY created_at DESC,id DESC OFFSET %s)",
                (METRICS_LIMIT,),
            )

    async def library_performance(self, model: str | None = None) -> dict:
        async with self.pool.connection() as conn:
            chats = await (
                await conn.execute(
                    "SELECT id,created_at,model,outcome,duration_ms,search_ms,first_token_ms,"
                    "output_tokens,tokens_per_second FROM rag.chat_metrics "
                    "ORDER BY created_at DESC,id DESC LIMIT %s",
                    (METRICS_LIMIT,),
                )
            ).fetchall()
            ingestions = await (
                await conn.execute(
                    "SELECT id,document_name,created_at,outcome,duration_ms,chunks,extraction_ms,"
                    "embedding_ms,chunks_per_second FROM rag.ingestion_metrics "
                    "ORDER BY created_at DESC,id DESC LIMIT %s",
                    (METRICS_LIMIT,),
                )
            ).fetchall()
        return performance_summary(chats, ingestions, model)

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

    async def finish(
        self,
        document_id: UUID,
        chunks: list[dict],
        indexing_metrics: dict | None = None,
        operation_started: float | None = None,
    ) -> bool:
        async with self.pool.connection() as conn:
            parent = await (
                await conn.execute(
                    "SELECT id FROM rag.documents WHERE id=%s AND status='processing' FOR UPDATE",
                    (document_id,),
                )
            ).fetchone()
            if parent is None:  # Deleted while extraction was running.
                return False
            await conn.execute("DELETE FROM rag.chunks WHERE document_id=%s", (document_id,))
            async with conn.cursor() as cur:
                await cur.executemany(
                    "INSERT INTO rag.chunks "
                    "(id, document_id, ordinal, page, content, embedding, token_count) "
                    "VALUES (%(id)s,%(document_id)s,%(ordinal)s,%(page)s,%(content)s,"
                    "%(embedding)s::public.vector,%(token_count)s)",
                    [{"token_count": None, **chunk} for chunk in chunks],
                )
            if indexing_metrics is not None and operation_started is not None:
                indexing_metrics["duration_ms"] = round(
                    (perf_counter() - operation_started) * 1000, 3
                )
            await conn.execute(
                "UPDATE rag.documents SET status='ready', chunk_count=%s, error=NULL, "
                "indexing_metrics=%s,updated_at=now() WHERE id=%s",
                (len(chunks), Jsonb(indexing_metrics) if indexing_metrics else None, document_id),
            )
            return True

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
