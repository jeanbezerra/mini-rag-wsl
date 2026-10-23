-- pgvector is provisioned by the database administrator, never the API role.
CREATE SCHEMA IF NOT EXISTS rag;
CREATE TABLE IF NOT EXISTS rag.schema_migrations (
    version integer PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS rag.documents (
    id uuid PRIMARY KEY,
    name text NOT NULL,
    extension text NOT NULL,
    sha256 text NOT NULL UNIQUE,
    size_bytes bigint NOT NULL CHECK (size_bytes > 0),
    status text NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'processing', 'ready', 'error')),
    chunk_count integer NOT NULL DEFAULT 0 CHECK (chunk_count >= 0),
    error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS rag.chunks (
    id uuid PRIMARY KEY,
    document_id uuid NOT NULL REFERENCES rag.documents(id) ON DELETE CASCADE,
    ordinal integer NOT NULL CHECK (ordinal >= 0),
    page integer CHECK (page > 0),
    content text NOT NULL,
    embedding public.vector(384) NOT NULL,
    search_vector tsvector GENERATED ALWAYS AS
        (to_tsvector('pg_catalog.portuguese'::regconfig, content)) STORED,
    UNIQUE (document_id, ordinal)
);
CREATE INDEX IF NOT EXISTS documents_queue_idx ON rag.documents (created_at, id)
    WHERE status = 'queued';
CREATE INDEX IF NOT EXISTS chunks_document_idx ON rag.chunks (document_id);
CREATE INDEX IF NOT EXISTS chunks_search_idx ON rag.chunks USING gin (search_vector);
-- Exact cosine search is deliberate for this small local corpus: no ANN recall loss
-- or costly HNSW construction on the same CPU used for inference.
CREATE TABLE IF NOT EXISTS rag.settings (
    key text PRIMARY KEY,
    value text NOT NULL
);
GRANT USAGE ON SCHEMA rag TO rag_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON rag.documents, rag.chunks TO rag_app;
GRANT SELECT ON rag.settings TO rag_app;
INSERT INTO rag.schema_migrations (version) VALUES (1) ON CONFLICT DO NOTHING;

-- v2: one global document, separate from the immutable embedding-index identity.
-- The API can update this row but cannot insert/delete it or change the schema.
CREATE TABLE IF NOT EXISTS rag.runtime_settings (
    singleton boolean PRIMARY KEY DEFAULT true,
    config_values jsonb NOT NULL DEFAULT '{}'::jsonb,
    revision bigint NOT NULL DEFAULT 0,
    updated_at timestamptz,
    CONSTRAINT runtime_settings_singleton CHECK (singleton),
    CONSTRAINT runtime_settings_values_object CHECK (jsonb_typeof(config_values) = 'object'),
    CONSTRAINT runtime_settings_revision_nonnegative CHECK (revision >= 0)
);
INSERT INTO rag.runtime_settings (singleton) VALUES (true) ON CONFLICT DO NOTHING;
GRANT SELECT ON rag.runtime_settings TO rag_app;
GRANT UPDATE (config_values, revision, updated_at) ON rag.runtime_settings TO rag_app;
INSERT INTO rag.schema_migrations (version) VALUES (2) ON CONFLICT DO NOTHING;

-- v3: measurements are nullable for pre-existing documents; no model-dependent
-- backfill or vector rewrite runs during an upgrade.
ALTER TABLE rag.documents ADD COLUMN IF NOT EXISTS indexing_metrics jsonb;
ALTER TABLE rag.chunks ADD COLUMN IF NOT EXISTS token_count integer
    CONSTRAINT chunks_token_count_range CHECK (token_count BETWEEN 1 AND 128);
CREATE TABLE IF NOT EXISTS rag.chat_metrics (
    id uuid PRIMARY KEY,
    created_at timestamptz NOT NULL DEFAULT now(),
    model text NOT NULL,
    outcome text NOT NULL CHECK (outcome IN ('completed', 'no_sources', 'error', 'cancelled')),
    duration_ms double precision NOT NULL CHECK (duration_ms >= 0),
    wait_ms double precision CHECK (wait_ms >= 0),
    search_ms double precision CHECK (search_ms >= 0),
    embedding_ms double precision CHECK (embedding_ms >= 0),
    first_token_ms double precision CHECK (first_token_ms >= 0),
    output_tokens integer CHECK (output_tokens >= 0),
    tokens_per_second double precision CHECK (tokens_per_second >= 0),
    source_count integer NOT NULL DEFAULT 0 CHECK (source_count >= 0),
    settings jsonb NOT NULL CHECK (jsonb_typeof(settings) = 'object')
);
CREATE INDEX IF NOT EXISTS chat_metrics_recent_idx
    ON rag.chat_metrics (created_at DESC, id DESC);
CREATE TABLE IF NOT EXISTS rag.ingestion_metrics (
    id uuid PRIMARY KEY,
    document_id uuid REFERENCES rag.documents(id) ON DELETE SET NULL,
    document_name text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    outcome text NOT NULL CHECK (outcome IN ('completed', 'error')),
    duration_ms double precision NOT NULL CHECK (duration_ms >= 0),
    extraction_ms double precision CHECK (extraction_ms >= 0),
    embedding_ms double precision CHECK (embedding_ms >= 0),
    chunks integer CHECK (chunks >= 0),
    chunks_per_second double precision CHECK (chunks_per_second >= 0),
    settings jsonb NOT NULL CHECK (jsonb_typeof(settings) = 'object')
);
CREATE INDEX IF NOT EXISTS ingestion_metrics_recent_idx
    ON rag.ingestion_metrics (created_at DESC, id DESC);
GRANT SELECT, INSERT, DELETE ON rag.chat_metrics, rag.ingestion_metrics TO rag_app;
INSERT INTO rag.schema_migrations (version) VALUES (3) ON CONFLICT DO NOTHING;
