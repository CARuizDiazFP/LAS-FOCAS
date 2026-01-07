# Nombre de archivo: firewall_hardening.sh
# Ubicación de archivo: scripts/firewall_hardening.sh
# Descripción: Endurecimiento de iptables y rp_filter para LAS-FOCAS (idempotente y listo para persistir)

#!/usr/bin/env bash
set -euo pipefail

WEB_HOST=${WEB_HOST:-192.168.241.28}
WEB_PORT=${WEB_PORT:-8080}
WEB_ALLOWED_SUBNETS=${WEB_ALLOWED_SUBNETS:-"190.12.96.0/24"}
ALLOW_LOCALHOST=${ALLOW_LOCALHOST:-true}
DOCKER_NET_CIDR=${DOCKER_NET_CIDR:-172.18.0.0/16}
MGMT_IFACE=${MGMT_IFACE:-ens224}
RP_DEFAULT_VALUE=${RP_DEFAULT_VALUE:-1}
RP_MGMT_VALUE=${RP_MGMT_VALUE:-2}
SYSCTL_CONF=${SYSCTL_CONF:-/etc/sysctl.d/99-lasfocas.conf}
PERSIST_RULES=${PERSIST_RULES:-false}

require_root() {
  if [[ ${EUID:-0} -ne 0 ]]; then
    echo "[ERROR] Ejecuta este script como root" >&2
    exit 1
  fi
}

ensure_rule() {
  local chain=$1; shift
  if ! iptables -C "$chain" "$@" >/dev/null 2>&1; then
    iptables -I "$chain" 1 "$@"
  fi
}

ensure_rule_end() {
  local chain=$1; shift
  if ! iptables -C "$chain" "$@" >/dev/null 2>&1; then
    iptables -A "$chain" "$@"
  fi
}

configure_input_chain() {
  if [[ "$ALLOW_LOCALHOST" == "true" ]]; then
    ensure_rule INPUT -p tcp -s 127.0.0.1/32 -d "$WEB_HOST" --dport "$WEB_PORT" -j ACCEPT
  fi
  for subnet in $WEB_ALLOWED_SUBNETS; do
    ensure_rule INPUT -p tcp -s "$subnet" -d "$WEB_HOST" --dport "$WEB_PORT" -j ACCEPT
  done
  ensure_rule_end INPUT -p tcp -d "$WEB_HOST" --dport "$WEB_PORT" -j DROP
}

configure_docker_user_chain() {
  ensure_rule DOCKER-USER -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
  for subnet in $WEB_ALLOWED_SUBNETS; do
    ensure_rule DOCKER-USER -p tcp -s "$subnet" --dport "$WEB_PORT" -j ACCEPT
  done
  ensure_rule_end DOCKER-USER -p tcp --dport "$WEB_PORT" -j DROP
}

configure_nat() {
  if ! iptables -t nat -C POSTROUTING -s "$DOCKER_NET_CIDR" -o "$MGMT_IFACE" -j MASQUERADE >/dev/null 2>&1; then
    iptables -t nat -A POSTROUTING -s "$DOCKER_NET_CIDR" -o "$MGMT_IFACE" -j MASQUERADE
  fi
}

set_rp_filter() {
  sysctl -w net.ipv4.conf.all.rp_filter="$RP_DEFAULT_VALUE" >/dev/null
  for path in /proc/sys/net/ipv4/conf/*/rp_filter; do
    iface=$(basename "$(dirname "$path")")
    desired="$RP_DEFAULT_VALUE"
    if [[ "$iface" == "$MGMT_IFACE" ]]; then
      desired="$RP_MGMT_VALUE"
    fi
    current=$(cat "$path")
    if [[ "$current" != "$desired" ]]; then
      echo "$desired" > "$path"
      sysctl -w net.ipv4.conf."$iface".rp_filter="$desired" >/dev/null
    fi
  done
}

persist_sysctl() {
  cat > "$SYSCTL_CONF" <<EOF
net.ipv4.conf.all.rp_filter=$RP_DEFAULT_VALUE
net.ipv4.conf.default.rp_filter=$RP_DEFAULT_VALUE
net.ipv4.conf.$MGMT_IFACE.rp_filter=$RP_MGMT_VALUE
EOF
}

maybe_persist_iptables() {
  if [[ "$PERSIST_RULES" == "true" ]]; then
    if command -v netfilter-persistent >/dev/null 2>&1; then
      netfilter-persistent save
    elif command -v service >/dev/null 2>&1 && service iptables-persistent status >/dev/null 2>&1; then
      service iptables-persistent save
    else
      echo "[WARN] iptables-persistent/netfilter-persistent no está instalado; instala y guarda manualmente" >&2
    fi
  fi
}

main() {
  require_root
  command -v iptables >/dev/null 2>&1 || { echo "[ERROR] iptables no disponible" >&2; exit 1; }
  configure_input_chain
  configure_docker_user_chain
  configure_nat
  set_rp_filter
  persist_sysctl
  maybe_persist_iptables
  echo "[OK] Reglas aplicadas. Verifica con: iptables -S INPUT; iptables -S DOCKER-USER; iptables -t nat -S POSTROUTING"
  echo "[OK] rp_filter: consulta con sysctl net.ipv4.conf.all.rp_filter net.ipv4.conf.$MGMT_IFACE.rp_filter"
}

main "$@"
