#!/usr/bin/env bash
set -Eeuo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
umask 077
backup_dir="backups/$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p -- "$backup_dir"
echo 'Pausando a API para manter documentos e banco consistentes...'
docker compose stop api
trap 'docker compose start api >/dev/null' EXIT
docker compose exec -T db pg_dump -U postgres -d mini_rag --format=custom > "$backup_dir/database.dump"
docker compose run --rm --no-deps --user 0 --entrypoint tar api -C /data -czf - . > "$backup_dir/app-data.tar.gz"
sha256sum "$backup_dir/database.dump" "$backup_dir/app-data.tar.gz" > "$backup_dir/SHA256SUMS"
echo "Backup criado em $backup_dir. Guarde também o .env em local seguro e teste a restauração em outro projeto Compose."
