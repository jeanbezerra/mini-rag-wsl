#!/usr/bin/env bash
set -Eeuo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

command -v docker >/dev/null || { echo 'Instale Docker Engine + Compose v2 no Ubuntu, ou habilite a integração WSL do Docker Desktop/Rancher Desktop. Veja README.md.' >&2; exit 1; }
docker compose version >/dev/null
docker info >/dev/null 2>&1 || { echo 'O daemon Docker não está acessível. Inicie seu runtime Docker e confira a integração com esta distribuição WSL.' >&2; exit 1; }

if [[ -r /etc/os-release ]]; then
  . /etc/os-release
  if [[ "${ID:-}" != ubuntu || "${VERSION_ID%%.*}" -lt 24 ]]; then
    echo 'Este projeto tem como alvo Ubuntu 24.04+ no WSL2.' >&2
    exit 1
  fi
fi

if [[ ! -f .env ]]; then
  command -v openssl >/dev/null || { echo 'Instale openssl para gerar senhas locais.' >&2; exit 1; }
  umask 077
  cp .env.example .env
  chmod 600 .env
  for key in POSTGRES_PASSWORD APP_DB_PASSWORD MIGRATOR_DB_PASSWORD; do
    secret=$(openssl rand -hex 24)
    sed -i "s/^${key}=.*/${key}=${secret}/" .env
  done
  # Keep a modest default; more threads may make inference slower.
  processors=$(getconf _NPROCESSORS_ONLN)
  threads=$(( processors < 4 ? processors : 4 ))
  sed -i "s/^CPU_THREADS=.*/CPU_THREADS=${threads}/" .env
  echo '.env criado com três senhas aleatórias. Guarde este arquivo.'
fi

if grep -Eq '^((POSTGRES|APP_DB|MIGRATOR_DB)_PASSWORD)=CHANGE_ME' .env; then
  echo 'Substitua as senhas CHANGE_ME no .env por senhas alfanuméricas únicas, ou remova somente o .env ainda não utilizado e execute novamente.' >&2
  exit 1
fi
# The passwords are interpolated into connection URLs; reject ambiguous values.
for key in POSTGRES_PASSWORD APP_DB_PASSWORD MIGRATOR_DB_PASSWORD; do
  value=$(sed -n "s/^${key}=//p" .env)
  if [[ ! "$value" =~ ^[A-Za-z0-9]{16,}$ ]]; then
    echo "${key} deve conter pelo menos 16 letras/números, sem aspas ou espaços." >&2
    exit 1
  fi
done

if [[ "$PWD" == /mnt/* ]]; then
  echo 'Dica: para melhor I/O no WSL, clone o repositório em ~/projetos/mini-rag-wsl.'
fi
docker compose config --quiet
docker compose up --build -d
echo
echo 'Aplicação iniciando. Frontend: http://localhost:'"$(sed -n 's/^APP_PORT=//p' .env | head -n1)"
echo 'O primeiro uso baixa o modelo (~1,4 GB) e os embeddings. Acompanhe:'
echo '  docker compose logs -f model-init api'
echo 'Verifique: bash scripts/doctor.sh'
