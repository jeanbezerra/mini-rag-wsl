#!/usr/bin/env bash
# Install host prerequisites only. Application services run in Docker Compose.
set -Eeuo pipefail

runtime=auto
key_file=''
sources_file=''
apt_updated=false

usage() {
  cat <<'HELP'
Uso: bash scripts/install-deps.sh [--runtime auto|engine|desktop]

  auto     Reutiliza Docker disponível ou integração Desktop/Rancher detectada.
           Se não houver runtime, instala Docker Engine no Ubuntu (padrão).
  engine   Instala/completa Docker Engine, Buildx e Compose no Ubuntu.
  desktop  Usa a integração WSL do Docker Desktop/Rancher, sem instalar Engine.

Execute no Ubuntu 24.04+ como seu usuário habitual. O script usa sudo quando
precisa instalar pacotes. Não inicia o bootstrap nem reinicia o WSL.
HELP
}

fail() { printf 'Erro: %s\n' "$*" >&2; exit 1; }
cleanup() {
  [[ -z "$key_file" ]] || rm -f -- "$key_file"
  [[ -z "$sources_file" ]] || rm -f -- "$sources_file"
}
trap cleanup EXIT
trap 'printf "Instalação interrompida na linha %s. Corrija o erro acima e execute novamente.\n" "$LINENO" >&2' ERR

while (($#)); do
  case "$1" in
    --runtime)
      (($# >= 2)) || fail 'Informe auto, engine ou desktop após --runtime.'
      runtime=$2
      shift 2
      ;;
    -h|--help) usage; exit 0 ;;
    *) fail "Opção desconhecida: $1. Use --help." ;;
  esac
done
case "$runtime" in auto|engine|desktop) ;; *) fail 'Runtime deve ser auto, engine ou desktop.' ;; esac

[[ -r /etc/os-release ]] || fail 'Execute este script dentro do Ubuntu WSL.'
# shellcheck disable=SC1091
. /etc/os-release
ubuntu_version=${VERSION_ID:-}
ubuntu_major=${ubuntu_version%%.*}
[[ ${ID:-} == ubuntu && $ubuntu_major =~ ^[0-9]+$ && $ubuntu_major -ge 24 ]] \
  || fail 'Ubuntu 24.04 ou superior é obrigatório.'
architecture=$(dpkg --print-architecture)
case "$architecture" in amd64|arm64) ;; *) fail 'Este projeto requer Ubuntu amd64 ou arm64.' ;; esac
if ((EUID == 0)); then target_user=${SUDO_USER:-root}; else target_user=$(id -un); fi
id "$target_user" >/dev/null || fail "Usuário inválido: $target_user"

as_root() {
  if ((EUID == 0)); then
    "$@"
  else
    command -v sudo >/dev/null || fail 'sudo não está instalado. Execute o instalador como root usando o usuário correto em SUDO_USER.'
    sudo -- "$@"
  fi
}

installed() {
  [[ $(dpkg-query -W -f='${Status}' "$1" 2>/dev/null) == *' ok installed' ]]
}

update_apt() {
  if [[ $apt_updated == false ]]; then
    as_root apt-get update
    apt_updated=true
  fi
}

install_packages() {
  update_apt
  as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "$@"
}

missing=()
for package in ca-certificates curl git openssl coreutils grep sed passwd; do
  installed "$package" || missing+=("$package")
done
if ((${#missing[@]})); then
  printf 'Instalando dependências básicas: %s\n' "${missing[*]}"
  install_packages "${missing[@]}"
fi

docker_path=$(command -v docker || true)
external_runtime=false
if [[ -n $docker_path ]]; then
  resolved_docker=$(readlink -f -- "$docker_path" || printf '%s' "$docker_path")
  socket_path=$(readlink -f -- /var/run/docker.sock || true)
  context=$(docker context show 2>/dev/null || true)
  case "$resolved_docker $socket_path $context" in
    *docker-desktop*|*rancher-desktop*|*'Rancher Desktop'*|*desktop-linux*) external_runtime=true ;;
  esac
fi

ready() {
  command -v docker >/dev/null \
    && docker compose version >/dev/null 2>&1 \
    && docker buildx version >/dev/null 2>&1 \
    && docker info >/dev/null 2>&1
}

success() {
  docker --version
  docker compose version
  docker buildx version
  printf '\nDependências prontas. Na raiz do repositório, execute como seu usuário habitual:\n'
  printf '  bash scripts/bootstrap.sh\n'
}

if [[ $runtime == auto ]] && ready \
  && { ((EUID != 0)) || [[ $target_user == root || $external_runtime == true ]]; }; then
  success
  exit 0
fi
if [[ $runtime == auto ]]; then
  if [[ $external_runtime == true ]]; then runtime=desktop; else runtime=engine; fi
fi
if [[ $runtime == desktop ]]; then
  ready || fail 'A integração Desktop/Rancher ainda não está pronta. Inicie o aplicativo no Windows e habilite esta distribuição nas configurações WSL. Confirme docker info, docker compose version e docker buildx version; execute este instalador novamente.'
  success
  exit 0
fi
[[ $external_runtime == false ]] \
  || fail 'Foi detectada integração Desktop/Rancher. Use --runtime desktop; para Engine nativo, desabilite antes essa integração e ajuste seu PATH/contexto Docker.'

if [[ $(cat /proc/1/comm) != systemd ]]; then
  missing_systemd=()
  for package in systemd systemd-sysv; do
    installed "$package" || missing_systemd+=("$package")
  done
  if ((${#missing_systemd[@]})); then install_packages "${missing_systemd[@]}"; fi
  cat >&2 <<'SYSTEMD'
O Docker Engine local precisa do systemd neste WSL.
Edite /etc/wsl.conf com sudo, preservando as outras configurações, e adicione
(ou ajuste a seção [boot] existente):

  [boot]
  systemd=true

Depois, salve seus trabalhos e execute no PowerShell do Windows:
  wsl --shutdown

Esse comando encerra todas as distribuições WSL. Reabra o Ubuntu e execute
novamente: bash scripts/install-deps.sh --runtime engine
SYSTEMD
  exit 2
fi

if ! command -v dockerd >/dev/null \
  || ! docker compose version >/dev/null 2>&1 \
  || ! docker buildx version >/dev/null 2>&1; then
  conflicts=()
  for package in docker.io docker-compose docker-compose-v2 docker-doc docker-buildx podman-docker containerd runc; do
    if installed "$package"; then conflicts+=("$package"); fi
  done
  if ((${#conflicts[@]})); then
    fail "Há pacotes conflitantes com Docker CE: ${conflicts[*]}. Configure o runtime existente com Compose/Buildx ou migre esses pacotes conforme a documentação Docker. Nenhum pacote foi removido."
  fi
  missing_docker=()
  for package in docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin; do
    installed "$package" || missing_docker+=("$package")
  done
  ((${#missing_docker[@]})) \
    || fail 'Os pacotes Docker CE já estão instalados, mas o daemon ou os plugins Compose/Buildx não estão acessíveis. Confira o PATH e a instalação dos plugins.'

  # Reuse an existing official repository, including older .list configurations.
  repository_found=false
  for source in /etc/apt/sources.list /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources; do
    if [[ -f $source ]] && grep -qE '^[^#]*download\.docker\.com/linux/ubuntu' "$source"; then
      repository_found=true
      break
    fi
  done
  if [[ $repository_found == false ]]; then
    [[ ! -e /etc/apt/sources.list.d/docker.sources ]] \
      || fail 'docker.sources já existe com configuração diferente. Revise esse arquivo antes de continuar.'
    codename=${UBUNTU_CODENAME:-${VERSION_CODENAME:-}}
    [[ $codename =~ ^[a-z][a-z0-9-]*$ ]] || fail 'Não foi possível identificar o codinome do Ubuntu.'
    key_file=$(mktemp)
    sources_file=$(mktemp)
    curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 \
      https://download.docker.com/linux/ubuntu/gpg --output "$key_file"
    cat > "$sources_file" <<SOURCES
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $codename
Components: stable
Architectures: $architecture
Signed-By: /etc/apt/keyrings/docker.asc
SOURCES
    as_root install -m 0755 -d /etc/apt/keyrings
    as_root install -m 0644 "$key_file" /etc/apt/keyrings/docker.asc
    as_root install -m 0644 "$sources_file" /etc/apt/sources.list.d/docker.sources
    apt_updated=false
  fi
  install_packages "${missing_docker[@]}"
fi

docker compose version >/dev/null 2>&1 || fail 'O plugin Compose continua indisponível. Confira o PATH e a instalação de docker-compose-plugin.'
docker buildx version >/dev/null 2>&1 || fail 'O plugin Buildx continua indisponível. Confira o PATH e a instalação de docker-buildx-plugin.'
as_root systemctl enable --now docker.service
group_added=false
if [[ $target_user != root ]]; then
  as_root groupadd --force docker
  if ! id -nG "$target_user" | tr ' ' '\n' | grep -qx docker; then
    printf 'Adicionando %s ao grupo docker para administrar o daemon sem sudo.\n' "$target_user"
    as_root usermod -aG docker "$target_user"
    group_added=true
  fi
fi

if ready; then
  if ((EUID == 0)) && [[ $target_user != root && $group_added == true ]]; then
    printf '\nDocker instalado e daemon ativo. Na sessão de %s, execute:\n' "$target_user"
    printf '  newgrp docker\n  docker info\n  bash scripts/bootstrap.sh\n'
    exit 2
  fi
  success
else
  # Verify the daemon itself separately from this shell's group/context settings.
  as_root docker --host unix:///var/run/docker.sock info >/dev/null \
    || fail 'O daemon não iniciou. Verifique: sudo journalctl -u docker.service --no-pager -n 50'
  printf '\nDocker instalado e daemon ativo. A sessão atual ainda não tem acesso.\n'
  printf 'Ative o grupo em um novo shell e teste:\n'
  printf '  newgrp docker\n  docker info\n  bash scripts/bootstrap.sh\n'
  printf 'Se necessário, confira também DOCKER_HOST e docker context ls.\n'
  exit 2
fi
