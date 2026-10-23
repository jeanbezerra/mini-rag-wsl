#!/usr/bin/env bash
# Prepare this Ubuntu WSL distribution for Docker CE; preview is the default.
set -Eeuo pipefail

apply=false
delete_cluster_data=false
mode=''
usage() {
  cat <<'HELP'
Uso: bash scripts/cleanup-wsl.sh [--dry-run | --apply] [--delete-cluster-data]

  --dry-run              Mostra o plano, sem alterar o sistema (padrão).
  --apply                Remove os pacotes locais indicados no plano.
  --delete-cluster-data  Autoriza reset do nó kubeadm local, necessário se houver
                         um nó configurado. Pode destruir dados dos pods locais.

Escopo: Kubernetes instalado por APT/kubeadm e pacotes conflitantes com Docker CE
no Ubuntu 24.04+ WSL. Reconhece pacotes held. Preserva Docker CE, seus volumes,
kubeconfig do usuário e distribuições WSL. Não altera aplicativos Windows.
K3s, RKE2, MicroK8s e k0s exigem seus próprios procedimentos de desinstalação.
HELP
}
fail() { printf 'Erro: %s\n' "$*" >&2; exit 1; }
while (($#)); do
  case "$1" in
    --apply|--dry-run)
      [[ -z $mode || $mode == "$1" ]] || fail '--apply e --dry-run são mutuamente exclusivos.'
      mode=$1
      [[ $1 != --apply ]] || apply=true
      ;;
    --delete-cluster-data) delete_cluster_data=true ;;
    -h|--help) usage; exit 0 ;;
    *) fail "Opção desconhecida: $1. Use --help." ;;
  esac
  shift
done

[[ -r /etc/os-release ]] || fail 'Execute no Ubuntu WSL.'
# shellcheck disable=SC1091
. /etc/os-release
ubuntu_version=${VERSION_ID:-}
ubuntu_major=${ubuntu_version%%.*}
[[ ${ID:-} == ubuntu && $ubuntu_major =~ ^[0-9]+$ && $ubuntu_major -ge 24 ]] \
  || fail 'Este script requer Ubuntu 24.04 ou superior.'
if [[ -z ${WSL_DISTRO_NAME:-} ]] && ! grep -qi microsoft /proc/sys/kernel/osrelease; then
  fail 'Este script é destinado a uma distribuição Ubuntu no WSL.'
fi

as_root() {
  if ((EUID == 0)); then "$@"; else
    command -v sudo >/dev/null || fail 'sudo não está disponível. Execute como root dentro deste Ubuntu.'
    sudo -- "$@"
  fi
}
run() {
  printf '  '
  printf '%q ' "$@"
  printf '\n'
  if [[ $apply == true ]]; then as_root "$@"; fi
}
installed() {
  # Kubernetes packages are often held; `${Status}` can be "hold ok installed".
  [[ $(dpkg-query -W -f='${Status}' "$1" 2>/dev/null) == *' ok installed' ]]
}
unit_loaded() {
  command -v systemctl >/dev/null \
    && [[ $(systemctl show --property=LoadState --value "$1" 2>/dev/null) == loaded ]]
}

kubernetes_packages=(kubeadm kubelet kubectl kubernetes-cni cri-tools kubernetes-client
  kubernetes-master kubernetes-node kube-apiserver kube-controller-manager kube-scheduler kube-proxy)
conflicting_packages=(docker.io docker-compose docker-compose-v2 docker-doc docker-buildx
  podman-docker containerd runc)
packages=()
for package in "${kubernetes_packages[@]}" "${conflicting_packages[@]}"; do
  if installed "$package"; then packages+=("$package"); fi
done

other_kubernetes=()
for tool in k3s rke2 microk8s k0s; do
  if command -v "$tool" >/dev/null; then other_kubernetes+=("$tool"); fi
done
for directory in /var/lib/rancher/k3s /var/lib/rancher/rke2 /var/snap/microk8s /var/lib/k0s; do
  if [[ -d $directory ]]; then other_kubernetes+=("$directory"); fi
done

node_configured=false
if [[ -e /etc/kubernetes/admin.conf || -e /etc/kubernetes/kubelet.conf \
  || -e /var/lib/kubelet/config.yaml ]]; then
  node_configured=true
elif unit_loaded kubelet.service; then
  if [[ -d /etc/kubernetes || -d /var/lib/kubelet ]] \
    || systemctl is-active --quiet kubelet.service; then node_configured=true; fi
fi

printf 'Distribuição: %s | Modo: %s\n' "${WSL_DISTRO_NAME:-Ubuntu WSL}" "${mode:---dry-run}"
printf 'Pacotes selecionados: %s\n' "${packages[*]:-nenhum}"
printf 'Nó kubeadm local configurado: %s\n' "$node_configured"
if ((${#other_kubernetes[@]})); then
  printf 'Outras instalações Kubernetes detectadas: %s\n' "${other_kubernetes[*]}"
fi
docker_path=$(command -v docker || true)
if [[ -n $docker_path ]]; then
  resolved_docker=$(readlink -f -- "$docker_path" || printf '%s' "$docker_path")
  socket_path=$(readlink -f -- /var/run/docker.sock || true)
  context=$(docker context show 2>/dev/null || true)
  case "$resolved_docker $socket_path $context" in
    *docker-desktop*|*rancher-desktop*|*'Rancher Desktop'*|*desktop-linux*)
      printf '\nIntegração Desktop/Rancher detectada: %s\n' "$docker_path"
      printf 'Para usar Engine nativo, desative a integração desta distribuição no aplicativo Windows.\n'
      printf 'O Kubernetes gerenciado pelo aplicativo Windows deve ser desativado nele.\n'
      ;;
  esac
fi

# Preflight the solver before stopping anything or resetting a local node.
# APT may otherwise remove unrelated reverse dependencies, including Docker CE.
if ((${#packages[@]})); then
  if ! simulation=$(LC_ALL=C apt-get --simulate --no-auto-remove --allow-change-held-packages remove -- "${packages[@]}" 2>&1); then
    printf '%s\n' "$simulation" >&2
    fail 'A simulação APT falhou; nenhum serviço foi parado nem nó reinicializado.'
  fi
  while read -r action package _; do
    case "$action" in
      Remv|Purg)
        expected=false
        for selected in "${packages[@]}"; do
          if [[ ${package%%:*} == "$selected" ]]; then expected=true; break; fi
        done
        [[ $expected == true ]] \
          || fail "APT pretende remover também ${package:-pacote desconhecido}, fora do plano. Revise as dependências manualmente. Nenhuma alteração aplicada."
        ;;
      Inst|Conf) fail 'APT pretende instalar/configurar outros pacotes. Corrija o estado do APT antes da limpeza.' ;;
    esac
  done <<< "$simulation"
  printf '\nSimulação APT:\n%s\n' "$simulation"
fi

if ((${#other_kubernetes[@]})); then
  printf '\nUse o desinstalador oficial da instalação detectada antes de remover seu runtime.\n'
  printf 'K3s: https://docs.k3s.io/installation/uninstall\n'
  printf 'RKE2: https://docs.rke2.io/install/uninstall\n'
  printf 'MicroK8s: https://canonical.com/microk8s/docs\n'
  printf 'k0s: https://docs.k0sproject.io/stable/reset/\n'
  if [[ $apply == true ]]; then
    fail 'Esta limpeza não executa desinstaladores de outras distribuições Kubernetes.'
  fi
  exit 0
fi

if [[ $node_configured == true && $delete_cluster_data == false ]]; then
  printf '\nHá um nó Kubernetes configurado. Sua remoção exige --delete-cluster-data.\n'
  printf 'Essa opção autoriza parar pods e reinicializar a configuração local; salve seus dados antes.\n'
  printf 'Plano completo: bash scripts/cleanup-wsl.sh --delete-cluster-data\n'
  printf 'Aplicar: bash scripts/cleanup-wsl.sh --apply --delete-cluster-data\n'
  if [[ $apply == true ]]; then exit 2; fi
  exit 0
fi

printf '\nComandos do plano:\n'
systemd_active=false
if [[ $(cat /proc/1/comm) == systemd ]]; then systemd_active=true; fi
if [[ $apply == true && $systemd_active == false ]] \
  && { ((${#packages[@]})) || [[ $node_configured == true ]]; }; then
  fail 'systemd não está ativo. Habilite-o antes de remover serviços e pacotes do nó.'
fi
if [[ $node_configured == true ]]; then
  [[ -x /usr/bin/kubeadm ]] || fail 'kubeadm não está em /usr/bin/kubeadm. Recupere a ferramenta do nó antes de executar seu reset; nenhuma alteração aplicada.'
  cri_socket=''
  for socket in /run/containerd/containerd.sock /var/run/containerd/containerd.sock; do
    if [[ -S $socket ]]; then cri_socket="unix://$socket"; break; fi
  done
  [[ -n $cri_socket ]] || fail 'Socket CRI local do containerd ausente. Confira sudo systemctl status containerd; nenhuma alteração aplicada.'
  printf 'Reset local autorizado. A fase que remove membros do etcd é ignorada.\n'
  run /usr/bin/kubeadm reset --force --skip-phases=remove-etcd-member --cri-socket "$cri_socket"
fi

if [[ $systemd_active == true ]]; then
  for unit in kubelet.service kube-apiserver.service kube-controller-manager.service kube-scheduler.service kube-proxy.service; do
    if unit_loaded "$unit"; then run systemctl disable --now "$unit"; fi
  done
  if installed docker.io; then
    for unit in docker.socket docker.service; do
      if unit_loaded "$unit"; then run systemctl disable --now "$unit"; fi
    done
  fi
  if installed containerd && ! installed containerd.io && unit_loaded containerd.service; then
    run systemctl disable --now containerd.service
  fi
fi
if ((${#packages[@]})); then
  run env DEBIAN_FRONTEND=noninteractive apt-get -y --no-auto-remove --allow-change-held-packages remove -- "${packages[@]}"
fi

printf '\n'
if [[ $apply == true ]]; then
  printf 'Limpeza dos componentes selecionados concluída.\n'
else
  printf 'Simulação concluída; nenhum item foi removido. Use --apply para executar o plano.\n'
fi
printf 'Próximo passo: bash scripts/install-deps.sh --runtime engine\n'
printf 'Após preparar o Docker: bash scripts/bootstrap.sh\n'
printf 'Configurações CNI/iptables, kubeconfig e dados Docker não são purgados por este script.\n'
