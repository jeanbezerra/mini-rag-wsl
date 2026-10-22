#!/usr/bin/env bash
set -Eeuo pipefail

# This runs only against a NEW database volume, as the image's bootstrap owner.
# psql variables quote values as SQL literals, never as shell-built SQL.
psql -X --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  --set=ON_ERROR_STOP=1 \
  --set=app_password="$APP_DB_PASSWORD" \
  --set=migrator_password="$MIGRATOR_DB_PASSWORD" <<'SQL'
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON DATABASE mini_rag FROM PUBLIC;
CREATE ROLE rag_migrator LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION
  PASSWORD :'migrator_password';
CREATE ROLE rag_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION
  PASSWORD :'app_password';
GRANT CONNECT, CREATE ON DATABASE mini_rag TO rag_migrator;
GRANT CONNECT ON DATABASE mini_rag TO rag_app;
ALTER ROLE rag_app SET statement_timeout = '30s';
ALTER ROLE rag_app SET idle_in_transaction_session_timeout = '30s';
ALTER ROLE rag_app SET search_path = rag, public;
ALTER ROLE rag_migrator SET search_path = rag, public;
SQL
