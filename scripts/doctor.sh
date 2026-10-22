#!/usr/bin/env bash
set -Eeuo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
echo '=== Ambiente ==='
uname -r
[[ ! -r /etc/os-release ]] || cat /etc/os-release
docker compose version
docker info --format 'Docker {{.ServerVersion}} | CPUs {{.NCPU}} | RAM {{.MemTotal}} bytes'
echo '=== Serviços ==='
docker compose ps -a
echo '=== Banco e extensão ==='
docker compose exec -T db psql -X -v ON_ERROR_STOP=1 -U postgres -d mini_rag \
  -c "SELECT current_setting('server_version') AS postgres_version, (SELECT extversion FROM pg_extension WHERE extname = 'vector') AS vector_version, current_setting('data_checksums') AS checksums;" \
  -c "SELECT rolname, rolsuper, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname IN ('rag_app', 'rag_migrator');"
echo '=== Modelos baixados / carregados ==='
docker compose exec -T ollama ollama list
docker compose exec -T ollama ollama ps
echo '=== Saúde da aplicação ==='
docker compose exec -T api python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/api/health', timeout=10).read().decode())"
