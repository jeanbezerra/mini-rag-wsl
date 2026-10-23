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
