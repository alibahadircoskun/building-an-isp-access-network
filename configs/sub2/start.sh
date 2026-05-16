#!/usr/bin/env sh
set -eu

. /startup/ssh-common.sh

apk add --no-cache iproute2 iputils iperf3 curl bind-tools openssl
setup_sshd_alpine
ip addr add 192.168.2.2/24 dev eth1 || true
ip link set eth1 up
ip route replace default via 192.168.2.1

# Wait for default route to be reachable before generating traffic
for _ in $(seq 1 30); do
  ping -c 1 -W 1 -q 8.8.8.8 >/dev/null 2>&1 && break
  sleep 2
done

# Offset startup relative to sub-1 so flows appear interleaved in ntopng.
sleep 7

# Background traffic generation — different timing/protocol mix than sub-1
# so ntopng shows two distinct subscriber traffic patterns simultaneously.
generate_traffic() {
  while true; do
    ping -c 2 -q 8.8.8.8 >/dev/null 2>&1 || true
    dig @8.8.8.8 twitch.tv A +time=2 +tries=1 >/dev/null 2>&1 || true
    dig @8.8.8.8 cloudflare.com A +time=2 +tries=1 >/dev/null 2>&1 || true
    dig @8.8.8.8 reddit.com AAAA +time=2 +tries=1 >/dev/null 2>&1 || true
    curl -s --max-time 3 http://8.8.8.8/ >/dev/null 2>&1 || true
    curl -sk --max-time 3 https://8.8.8.8/ >/dev/null 2>&1 || true
    iperf3 -c 8.8.8.8 -t 5 -u -b 1M -p 5201 --connect-timeout 2000 >/dev/null 2>&1 || true
    sleep 20
  done
}

generate_traffic &

sleep infinity
