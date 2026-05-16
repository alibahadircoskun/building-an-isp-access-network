#!/usr/bin/env bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

. /startup/ssh-common.sh

apt-get update
apt-get install -y --no-install-recommends \
  ca-certificates curl iproute2 iptables iputils-ping tcpdump jq

setup_sshd_debian

# ntop repository and tools
curl -fsSL https://packages.ntop.org/apt/22.04/all/apt-ntop.deb -o /tmp/apt-ntop.deb
apt-get install -y /tmp/apt-ntop.deb
apt-get update
apt-get -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold" install -y --no-install-recommends ndpi ntopng

# Transparent bridge for inline path
for ifn in eth1 eth2 eth3; do
  for _ in $(seq 1 30); do
    ip link show "${ifn}" >/dev/null 2>&1 && break
    sleep 1
  done
  ip link show "${ifn}" >/dev/null 2>&1 || { echo "missing ${ifn}"; exit 1; }
done

ip link add br0 type bridge
ip link set eth1 master br0
ip link set eth2 master br0
ip link set eth3 master br0
ip link set eth1 up
ip link set eth2 up
ip link set eth3 up
ip link set br0 up

# Prevent bridge netfilter from breaking PPPoE discovery/session frames
if [[ -e /proc/sys/net/bridge/bridge-nf-call-iptables ]]; then
  sysctl -w net.bridge.bridge-nf-call-iptables=0
fi
if [[ -e /proc/sys/net/bridge/bridge-nf-call-ip6tables ]]; then
  sysctl -w net.bridge.bridge-nf-call-ip6tables=0
fi

# Optional advanced path (disabled by default):
# iptables -I FORWARD -j NFQUEUE --queue-num 0 --queue-bypass

redis-server --daemonize yes
exec ntopng /etc/ntopng/ntopng.conf
