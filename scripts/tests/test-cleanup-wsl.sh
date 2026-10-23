#!/usr/bin/env bash
# Validate cleanup plans in a read-only, network-isolated filesystem with mocks.
set -Eeuo pipefail

command -v bwrap >/dev/null || { printf 'Estes testes precisam do bubblewrap (bwrap).\n' >&2; exit 1; }
command -v python3 >/dev/null || { printf 'Estes testes precisam do Python 3 para criar o socket fictício.\n' >&2; exit 1; }
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
test_dir=$(mktemp -d)
trap 'rm -rf -- "$test_dir"' EXIT
cp -- "$script_dir/cleanup-wsl.sh" "$test_dir/cleanup-wsl.sh"
mkdir -p "$test_dir/bin"
for utility in awk basename cat cp dirname env find findmnt grep head id mkdir mktemp readlink realpath rm sed sort stat tail tr; do
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
  uname)
    case "${1:-}" in
      -r) printf '6.6.87.2-microsoft-standard-WSL2\n' ;;
      -m) printf 'x86_64\n' ;;
      *) printf 'Linux\n' ;;
    esac
    ;;
  cat)
    case "${1:-}" in
      /proc/1/comm) if [[ $TEST_SCENARIO == no-systemd ]]; then printf 'init\n'; else printf 'systemd\n'; fi ;;
      /proc/sys/kernel/osrelease) printf '6.6.87.2-microsoft-standard-WSL2\n' ;;
      /proc/version) printf 'Linux version 6.6.87.2-microsoft-standard-WSL2\n' ;;
      *) /bin/cat "$@" ;;
    esac
    ;;
  dpkg-query)
    package=${!#}
    case "$TEST_SCENARIO" in
      empty|unsupported|help|invalid|flag-missing-apply) exit 1 ;;
    esac
    case "$package" in
      kubeadm|kubelet|kubectl|kubernetes-cni|cri-tools)
        if [[ $* == *'db:Status-Status'* ]]; then printf 'installed'; else printf 'hold ok installed'; fi
        ;;
      containerd|runc|docker.io|docker-compose|docker-compose-v2|docker-doc|docker-buildx|podman-docker)
        if [[ $TEST_SCENARIO == preserve-docker && ( $package == docker.io || $package == containerd || $package == runc ) ]]; then exit 1; fi
        if [[ $* == *'db:Status-Status'* ]]; then printf 'installed'; else printf 'install ok installed'; fi
        ;;
      docker-ce|docker-ce-cli|containerd.io|docker-buildx-plugin|docker-compose-plugin)
        if [[ $TEST_SCENARIO == preserve-docker ]]; then
          if [[ $* == *'db:Status-Status'* ]]; then printf 'installed'; else printf 'install ok installed'; fi
        else exit 1; fi
        ;;
      *) exit 1 ;;
    esac
    ;;
  apt-get)
    simulation=false
    for argument in "$@"; do case "$argument" in --simulate|-s|--dry-run) simulation=true ;; esac; done
    if [[ $simulation == true ]]; then
      [[ $TEST_SCENARIO != apt-failure ]] || { printf 'Mock apt unavailable\n' >&2; exit 42; }
      [[ $TEST_SCENARIO != extra-dependency ]] || printf 'Remv ubuntu-minimal [1.0]\n'
      [[ $TEST_SCENARIO != apt-configure ]] || printf 'Conf unrelated-package (1.0 Ubuntu:24.04/noble [amd64])\n'
      [[ $TEST_SCENARIO != apt-install ]] || printf 'Inst unrelated-package (1.0 Ubuntu:24.04/noble [amd64])\n'
      removal=false
      for argument in "$@"; do
        if [[ $argument == remove || $argument == purge ]]; then removal=true; continue; fi
        if [[ $removal == true && $argument != -* ]]; then printf 'Remv %s [1.0]\n' "$argument"; fi
      done
    else
      : > /tmp/test-output/apt-applied
    fi
    ;;
  kubeadm) : > /tmp/test-output/reset ;;
  systemctl)
    case "${1:-}" in
      is-active)
        if [[ $TEST_SCENARIO == empty ]]; then exit 3; else printf 'active\n'; fi
        ;;
      list-unit-files) printf 'kubelet.service enabled\ncontainerd.service enabled\n' ;;
      show) if [[ $TEST_SCENARIO == empty ]]; then printf 'not-found\n'; else printf 'loaded\n'; fi ;;
      *) : > /tmp/test-output/services-applied ;;
    esac
    ;;
  snap)
    if [[ $TEST_SCENARIO == microk8s ]]; then
      printf 'Name Version Rev Tracking Publisher Notes\nmicrok8s 1.35 1 latest/stable canonical classic\n'
    else exit 1; fi
    ;;
  docker)
    case "${1:-} ${2:-}" in
      'context show') printf 'default\n' ;;
      *) printf 'Unexpected Docker action\n' >&2; exit 97 ;;
    esac
    ;;
  readlink)
    if [[ $TEST_SCENARIO == desktop && ${!#} == */docker ]]; then
      printf '/mnt/c/Program Files/Rancher Desktop/resources/resources/linux/bin/docker\n'
    else /usr/bin/readlink "$@"; fi
    ;;
  sudo)
    [[ ${1:-} != -- ]] || shift
    case "${1:-}" in
      -v|-n) exit 0 ;;
      apt-get|systemctl|kubeadm|/usr/bin/kubeadm|env) exec "$@" ;;
      *) printf 'Unexpected privileged action: %s\n' "${1:-}" >&2; exit 90 ;;
    esac
    ;;
  *) printf 'Unexpected mock: %s\n' "$name" >&2; exit 99 ;;
esac
MOCK
chmod +x "$test_dir/mock"
for utility in uname cat dpkg-query apt-get kubeadm systemctl snap sudo docker readlink; do
  ln -sf /tmp/test/mock "$test_dir/bin/$utility"
done

assert_absent() {
  if grep -Eq -- "$1" "$2"; then
    printf 'Operação inesperada no teste: %s\n' "$1" >&2
    cat "$2" >&2
    exit 1
  fi
}

run_case() {
  local scenario=$1 expected=$2
  shift 2
  local case_dir="$test_dir/$scenario" status=0 kubeadm_fixture="$test_dir/mock"
  mkdir -p "$case_dir/etc" "$case_dir/var/lib/docker/volumes" "$case_dir/run" \
    "$case_dir/output" "$case_dir/local-bin" "$case_dir/bin"
  printf 'ID=ubuntu\nVERSION_ID="24.04"\n' > "$case_dir/etc/os-release"
  printf 'DO NOT DELETE\n' > "$case_dir/var/lib/docker/volumes/sentinel"
  cp -a -- "$test_dir/bin/." "$case_dir/bin/"
  mkdir -p "$case_dir/run/containerd"
  if [[ $scenario != missing-socket ]]; then
    python3 -c 'import socket,sys; s=socket.socket(socket.AF_UNIX); s.bind(sys.argv[1]); s.close()' \
      "$case_dir/run/containerd/containerd.sock"
  fi
  if [[ $scenario != empty && $scenario != unsupported ]]; then
    mkdir -p "$case_dir/etc/kubernetes/manifests" "$case_dir/var/lib/kubelet"
    printf 'local fixture\n' > "$case_dir/etc/kubernetes/kubelet.conf"
    printf 'local fixture\n' > "$case_dir/var/lib/kubelet/config.yaml"
  fi
  if [[ $scenario == unsupported ]]; then printf 'ID=debian\nVERSION_ID="13"\n' > "$case_dir/etc/os-release"; fi
  if [[ $scenario == old-ubuntu ]]; then printf 'ID=ubuntu\nVERSION_ID="22.04"\n' > "$case_dir/etc/os-release"; fi
  if [[ $scenario == k3s ]]; then
    mkdir -p "$case_dir/var/lib/rancher/k3s"
  fi
  if [[ $scenario == microk8s ]]; then mkdir -p "$case_dir/var/snap/microk8s"; fi
  if [[ $scenario == rke2 ]]; then mkdir -p "$case_dir/var/lib/rancher/rke2"; fi
  if [[ $scenario == k0s ]]; then mkdir -p "$case_dir/var/lib/k0s"; fi
  if [[ $scenario == missing-kubeadm ]]; then
    kubeadm_fixture="$case_dir/kubeadm-disabled"
    printf '#!/bin/bash\nexit 98\n' > "$kubeadm_fixture"
    chmod -x "$kubeadm_fixture"
  fi
  : > "$case_dir/output/commands"
  bwrap --ro-bind / / --unshare-net --die-with-parent --dev /dev --tmpfs /tmp \
    --ro-bind "$test_dir" /tmp/test --ro-bind "$case_dir/bin" /tmp/test/bin \
    --ro-bind "$case_dir/etc" /etc --ro-bind "$case_dir/var" /var \
    --ro-bind "$case_dir/run" /run --ro-bind "$case_dir/local-bin" /usr/local/bin \
    --ro-bind "$kubeadm_fixture" /usr/bin/kubeadm \
    --bind "$case_dir/output" /tmp/test-output --clearenv \
    --setenv PATH /tmp/test/bin --setenv HOME /tmp --setenv LC_ALL C.UTF-8 \
    --setenv WSL_DISTRO_NAME Ubuntu-24.04 --setenv TEST_SCENARIO "$scenario" \
    /bin/bash /tmp/test/cleanup-wsl.sh "$@" \
    > "$case_dir/output/stdout" 2> "$case_dir/output/stderr" || status=$?
  if [[ $status != "$expected" ]]; then
    printf 'FALHOU %s: esperado exit %s, recebido %s\n' "$scenario" "$expected" "$status" >&2
    cat "$case_dir/output/stdout" "$case_dir/output/stderr" >&2
    exit 1
  fi
  local commands="$case_dir/output/commands"
  case "$scenario" in
    dry-run|held|desktop|flag-preview)
      [[ ! -e $case_dir/output/reset && ! -e $case_dir/output/apt-applied && ! -e $case_dir/output/services-applied ]]
      assert_absent '^sudo ' "$commands"
      if [[ $scenario == held ]]; then grep -q 'kubeadm' "$case_dir/output/stdout"; fi
      ;;
    apply|preserve-docker)
      [[ -e $case_dir/output/reset && -e $case_dir/output/apt-applied ]]
      grep -Eq '^kubeadm reset .*--skip-phases(=| )remove-etcd-member' "$commands"
      grep -Eq '^kubeadm reset .*--cri-socket(=| )unix:///run/containerd/containerd.sock' "$commands"
      grep -q '^systemctl .*kubelet' "$commands"
      grep -q '^apt-get .*--no-auto-remove' "$commands"
      grep -q '^apt-get .*--allow-change-held-packages' "$commands"
      assert_absent '^apt-get .*(docker-ce|containerd.io|docker-buildx-plugin|docker-compose-plugin)' "$commands"
      if [[ $scenario == preserve-docker ]]; then assert_absent '^systemctl disable --now (docker.socket|docker.service|containerd.service)$' "$commands"; fi
      local preview_line reset_line
      preview_line=$(grep -n '^apt-get --simulate ' "$commands")
      reset_line=$(grep -n '^kubeadm reset ' "$commands")
      (( ${preview_line%%:*} < ${reset_line%%:*} ))
      ;;
    missing-data|apt-failure|extra-dependency|apt-configure|apt-install|k3s|microk8s|rke2|k0s|unsupported|old-ubuntu|missing-socket|missing-kubeadm|no-systemd)
      [[ ! -e $case_dir/output/reset && ! -e $case_dir/output/apt-applied && ! -e $case_dir/output/services-applied ]]
      ;;
    empty)
      assert_absent '^(sudo|apt-get|kubeadm) ' "$commands"
      ;;
    help)
      assert_absent '^(dpkg-query|sudo|apt-get|systemctl|kubeadm) ' "$commands"
      ;;
    invalid|mode-conflict)
      [[ ! -s $commands ]]
      ;;
  esac
  assert_absent '^(kubectl|iptables|ip6tables|nft|wsl|wsl.exe|rm) ' "$commands"
  [[ $(cat "$case_dir/var/lib/docker/volumes/sentinel") == 'DO NOT DELETE' ]]
  printf 'PASS %s\n' "$scenario"
}

run_case dry-run 0
run_case held 0
run_case desktop 0
run_case missing-data 2 --apply
run_case apply 0 --apply --delete-cluster-data
run_case preserve-docker 0 --apply --delete-cluster-data
run_case apt-failure 1 --apply --delete-cluster-data
run_case extra-dependency 1 --apply --delete-cluster-data
run_case apt-configure 1 --apply --delete-cluster-data
run_case apt-install 1 --apply --delete-cluster-data
run_case empty 0 --apply
run_case k3s 1 --apply --delete-cluster-data
run_case microk8s 1 --apply --delete-cluster-data
run_case rke2 1 --apply --delete-cluster-data
run_case k0s 1 --apply --delete-cluster-data
run_case unsupported 1 --apply --delete-cluster-data
run_case old-ubuntu 1 --apply --delete-cluster-data
run_case missing-socket 1 --apply --delete-cluster-data
run_case missing-kubeadm 1 --apply --delete-cluster-data
run_case no-systemd 1 --apply --delete-cluster-data
run_case help 0 --help
run_case invalid 1 --unknown
run_case mode-conflict 1 --apply --dry-run
run_case flag-preview 0 --delete-cluster-data
