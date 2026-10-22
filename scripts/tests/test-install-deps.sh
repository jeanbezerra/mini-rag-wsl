#!/usr/bin/env bash
# Exercise the host installer without network, root access, or real package changes.
set -Eeuo pipefail

command -v bwrap >/dev/null || { printf 'Estes testes precisam do bubblewrap (bwrap).\n' >&2; exit 1; }
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
test_dir=$(mktemp -d)
trap 'rm -rf -- "$test_dir"' EXIT
cp -- "$script_dir/install-deps.sh" "$test_dir/install-deps.sh"
mkdir -p "$test_dir/bin"

# Only these utilities can run directly. Every privileged operation is mocked;
# bubblewrap also makes the host filesystem read-only and disconnects networking.
for utility in cat cp env grep mkdir mktemp readlink rm tr; do
  ln -s -- "$(command -v "$utility")" "$test_dir/bin/$utility"
done
cat > "$test_dir/mock" <<'MOCK'
#!/bin/bash
set -Eeuo pipefail
name=${0##*/}
printf '%s' "$name" >> /tmp/test-output/commands
printf ' %q' "$@" >> /tmp/test-output/commands
printf '\n' >> /tmp/test-output/commands
case "$name" in
  dpkg) printf 'amd64\n' ;;
  dpkg-query)
    package=${!#}
    case "$package" in
      git|openssl) [[ $TEST_SCENARIO == missing-base ]] || printf 'install ok installed' ;;
      ca-certificates|curl|coreutils|grep|sed|passwd|systemd|systemd-sysv) printf 'install ok installed' ;;
      docker-ce|docker-ce-cli|containerd.io|docker-buildx-plugin|docker-compose-plugin)
        if [[ $TEST_SCENARIO == plugin-broken ]] \
          || [[ $TEST_SCENARIO == missing-compose && $package != docker-compose-plugin ]]; then
          printf 'install ok installed'
        fi
        ;;
      docker.io) [[ $TEST_SCENARIO != conflict ]] || printf 'install ok installed' ;;
    esac
    ;;
  cat)
    if [[ ${1:-} == /proc/1/comm ]]; then
      if [[ $TEST_SCENARIO == no-systemd ]]; then printf 'init\n'; else printf 'systemd\n'; fi
    else /bin/cat "$@"; fi
    ;;
  readlink)
    if [[ $TEST_SCENARIO == desktop-offline ]]; then
      case "${!#}" in
        */docker) printf '/mnt/wsl/docker-desktop/cli-tools/usr/bin/docker\n'; exit 0 ;;
        /var/run/docker.sock) printf '/mnt/wsl/docker-desktop/shared-sockets/docker.sock\n'; exit 0 ;;
      esac
    fi
    /usr/bin/readlink "$@"
    ;;
  sudo)
    [[ ${1:-} != -- ]] || shift
    case "${1:-}" in
      env|apt-get|install|systemctl|groupadd|usermod|docker) TEST_AS_ROOT=1 exec "$@" ;;
      *) printf 'Comando sudo não permitido no teste: %s\n' "${1:-}" >&2; exit 90 ;;
    esac
    ;;
  apt-get)
    if [[ ${1:-} == install ]]; then
      for package in "$@"; do
        if [[ $package == docker-compose-plugin ]]; then : > /tmp/test-output/installed; fi
        if [[ $package == docker-ce-cli ]]; then
          : > /tmp/test-output/installed
          /bin/ln -sf /tmp/test/mock /tmp/bin/docker
          /bin/ln -sf /tmp/test/mock /tmp/bin/dockerd
        fi
      done
    fi
    ;;
  curl)
    while (($#)); do
      if [[ $1 == --output ]]; then
        [[ ${2:-} == /tmp/* ]] || exit 91
        printf 'MOCK DOCKER SIGNING KEY\n' > "$2"
        exit 0
      fi
      shift
    done
    exit 92
    ;;
  install)
    destination=${!#}
    case "$destination" in
      /etc/apt/keyrings) [[ $* == '-m 0755 -d /etc/apt/keyrings' ]] || exit 93 ;;
      /etc/apt/keyrings/docker.asc|/etc/apt/sources.list.d/docker.sources)
        source=${@: -2:1}
        [[ $source == /tmp/* ]] || exit 94
        /bin/cp -- "$source" "/tmp/test-output/${destination##*/}"
        ;;
      *) exit 95 ;;
    esac
    ;;
  systemctl) : > /tmp/test-output/started ;;
  groupadd) ;;
  usermod) : > /tmp/test-output/group-added ;;
  id)
    case "${1:-}" in
      -un) printf 'tester\n' ;;
      -nG)
        case "$TEST_SCENARIO" in
          native-stopped|missing-compose) printf 'tester docker\n' ;;
          *) printf 'tester\n' ;;
        esac
        ;;
      tester) printf 'uid=1000(tester) gid=1000(tester)\n' ;;
      *) exit 96 ;;
    esac
    ;;
  docker)
    case "${1:-} ${2:-}" in
      'context show')
        if [[ $TEST_SCENARIO == desktop-offline ]]; then printf 'desktop-linux\n'; else printf 'default\n'; fi
        ;;
      'compose version'|'buildx version')
        case "$TEST_SCENARIO" in
          ready|missing-base|sudo-ready-auto|desktop-offline|native-stopped) printf 'Docker plugin mock\n' ;;
          missing-compose)
            [[ $1 != compose || -f /tmp/test-output/installed ]] || exit 1
            printf 'Docker plugin mock\n'
            ;;
          plugin-broken) [[ $1 != compose ]] || exit 1; printf 'Docker plugin mock\n' ;;
          *) [[ -f /tmp/test-output/installed ]] || exit 1; printf 'Docker plugin mock\n' ;;
        esac
        ;;
      '--version ') printf 'Docker version mock\n' ;;
      'info ')
        case "$TEST_SCENARIO" in
          ready|missing-base) exit 0 ;;
          sudo-ready-auto) [[ $EUID == 0 ]] ;;
          native-stopped|missing-compose) [[ -f /tmp/test-output/started ]] ;;
          fresh|sudo-fresh) [[ -f /tmp/test-output/started ]] && [[ ${TEST_AS_ROOT:-0} == 1 || $EUID == 0 ]] ;;
          *) exit 1 ;;
        esac
        ;;
      '--host unix:///var/run/docker.sock') [[ -f /tmp/test-output/started ]] ;;
      *) printf 'Chamada Docker inesperada no teste\n' >&2; exit 97 ;;
    esac
    ;;
  dockerd) exit 98 ;;
  *) printf 'Mock inesperado: %s\n' "$name" >&2; exit 99 ;;
esac
MOCK
chmod +x "$test_dir/mock"
for utility in dpkg dpkg-query cat readlink sudo apt-get curl install systemctl groupadd usermod id; do
  ln -sf -- /tmp/test/mock "$test_dir/bin/$utility"
done

assert_absent() {
  if grep -Eq -- "$1" "$2"; then
    printf 'Operação inesperada no teste: %s\n' "$1" >&2
    exit 1
  fi
}

run_case() {
  local scenario=$1 expected=$2
  shift 2
  local case_dir="$test_dir/$scenario"
  mkdir -p "$case_dir/etc/apt/sources.list.d" "$case_dir/bin" "$case_dir/output"
  printf 'ID=ubuntu\nVERSION_ID="24.04"\nVERSION_CODENAME=noble\n' > "$case_dir/etc/os-release"
  cp -a -- "$test_dir/bin/." "$case_dir/bin/"
  case "$scenario" in
    fresh|sudo-fresh) ;;
    *) ln -s /tmp/test/mock "$case_dir/bin/docker" ;;
  esac
  case "$scenario" in
    native-stopped|sudo-ready-auto|plugin-broken|missing-compose) ln -s /tmp/test/mock "$case_dir/bin/dockerd" ;;
  esac
  if [[ $scenario == plugin-broken || $scenario == missing-compose ]]; then
    printf 'deb https://download.docker.com/linux/ubuntu noble stable\n' > "$case_dir/etc/apt/sources.list.d/docker.list"
  fi
  local status=0
  local sandbox_options=()
  if [[ $scenario == sudo-* ]]; then
    sandbox_options+=(--unshare-user --uid 0 --gid 0 --setenv SUDO_USER tester)
  fi
  bwrap --ro-bind / / --unshare-net --die-with-parent --dev /dev --tmpfs /tmp \
    --ro-bind "$test_dir" /tmp/test --ro-bind "$case_dir/bin" /tmp/test/bin \
    --ro-bind "$case_dir/etc" /etc --bind "$case_dir/output" /tmp/test-output \
    --clearenv --setenv PATH /tmp/bin:/tmp/test/bin \
    --setenv HOME /tmp --setenv LC_ALL C.UTF-8 --setenv TEST_SCENARIO "$scenario" \
    "${sandbox_options[@]}" \
    /bin/bash -c 'mkdir -p /tmp/bin; exec /bin/bash /tmp/test/install-deps.sh "$@"' -- "$@" \
    > "$case_dir/output/stdout" 2> "$case_dir/output/stderr" || status=$?
  if [[ $status != "$expected" ]]; then
    printf 'FALHOU %s: esperado exit %s, recebido %s\n' "$scenario" "$expected" "$status" >&2
    cat "$case_dir/output/stdout" "$case_dir/output/stderr" >&2
    exit 1
  fi
  case "$scenario" in
    ready)
      assert_absent '^(sudo|apt-get|systemctl|usermod) ' "$case_dir/output/commands"
      grep -q 'Dependências prontas' "$case_dir/output/stdout"
      ;;
    desktop-offline)
      assert_absent '^(apt-get|systemctl|usermod) ' "$case_dir/output/commands"
      grep -q 'integração Desktop/Rancher' "$case_dir/output/stderr"
      ;;
    missing-base)
      grep -q '^apt-get install -y --no-install-recommends git openssl$' "$case_dir/output/commands"
      [[ $(grep -c '^apt-get update$' "$case_dir/output/commands") == 1 ]]
      assert_absent '^(install|curl|systemctl|usermod) ' "$case_dir/output/commands"
      grep -q 'Dependências prontas' "$case_dir/output/stdout"
      ;;
    fresh|sudo-fresh)
      grep -q '^apt-get install -y --no-install-recommends docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin$' "$case_dir/output/commands"
      grep -q '^systemctl enable --now docker.service$' "$case_dir/output/commands"
      grep -q '^usermod -aG docker tester$' "$case_dir/output/commands"
      grep -q '^Suites: noble$' "$case_dir/output/docker.sources"
      grep -q '^Architectures: amd64$' "$case_dir/output/docker.sources"
      grep -q '^Signed-By: /etc/apt/keyrings/docker.asc$' "$case_dir/output/docker.sources"
      grep -q 'newgrp docker' "$case_dir/output/stdout"
      if [[ $scenario == sudo-fresh ]]; then
        assert_absent '^sudo ' "$case_dir/output/commands"
        grep -q 'Na sessão de tester' "$case_dir/output/stdout"
      fi
      ;;
    native-stopped)
      assert_absent '^(apt-get|install|curl|usermod) ' "$case_dir/output/commands"
      grep -q '^systemctl enable --now docker.service$' "$case_dir/output/commands"
      grep -q 'Dependências prontas' "$case_dir/output/stdout"
      ;;
    sudo-ready-auto)
      assert_absent '^(apt-get|install|curl|sudo) ' "$case_dir/output/commands"
      grep -q '^usermod -aG docker tester$' "$case_dir/output/commands"
      grep -q 'Na sessão de tester' "$case_dir/output/stdout"
      grep -q 'newgrp docker' "$case_dir/output/stdout"
      ;;
    plugin-broken)
      assert_absent '^(apt-get|install|curl|systemctl|usermod) ' "$case_dir/output/commands"
      grep -q 'Compose' "$case_dir/output/stderr"
      ;;
    missing-compose)
      grep -q '^apt-get install -y --no-install-recommends docker-compose-plugin$' "$case_dir/output/commands"
      assert_absent '^(install|curl|usermod) ' "$case_dir/output/commands"
      grep -q 'Dependências prontas' "$case_dir/output/stdout"
      ;;
    conflict)
      assert_absent '^(apt-get|install|curl|systemctl) ' "$case_dir/output/commands"
      grep -q 'pacotes conflitantes.*docker.io' "$case_dir/output/stderr"
      ;;
    no-systemd)
      assert_absent '^(apt-get|install|curl|systemctl) ' "$case_dir/output/commands"
      grep -q 'systemd=true' "$case_dir/output/stderr"
      ;;
    help)
      assert_absent '^(dpkg|sudo|apt-get|systemctl) ' "$case_dir/output/commands"
      grep -q '^Uso:' "$case_dir/output/stdout"
      ;;
    invalid|missing-runtime)
      [[ ! -s $case_dir/output/commands ]]
      ;;
  esac
  printf 'PASS %s\n' "$scenario"
}

run_case ready 0
run_case missing-base 0
run_case desktop-offline 1
run_case fresh 2 --runtime engine
run_case sudo-fresh 2 --runtime engine
run_case sudo-ready-auto 2
run_case native-stopped 0 --runtime engine
run_case conflict 1 --runtime engine
run_case no-systemd 2 --runtime engine
run_case plugin-broken 1 --runtime engine
run_case missing-compose 0 --runtime engine
run_case help 0 --help
run_case invalid 1 --runtime invalid
run_case missing-runtime 1 --runtime
