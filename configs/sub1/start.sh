#!/usr/bin/env sh
set -eu

. /startup/ssh-common.sh

apk add --no-cache iproute2 iputils iperf3 curl bind-tools openssl
setup_sshd_alpine
ip addr add 192.168.1.2/24 dev eth1 || true
ip link set eth1 up
ip route replace default via 192.168.1.1

# Wait for default route to be reachable before generating traffic
for _ in $(seq 1 30); do
  ping -c 1 -W 1 -q 8.8.8.8 >/dev/null 2>&1 && break
  sleep 2
done

# Background traffic generation — keeps ntopng DPI dashboard populated with
# classified flows (DNS, HTTP, TLS, ICMP) throughout the demo.
generate_traffic() {
  while true; do
    ping -c 4 -q 8.8.8.8 >/dev/null 2>&1 || true
    dig @8.8.8.8 google.com A +time=2 +tries=1 >/dev/null 2>&1 || true
    dig @8.8.8.8 youtube.com A +time=2 +tries=1 >/dev/null 2>&1 || true
    dig @8.8.8.8 netflix.com AAAA +time=2 +tries=1 >/dev/null 2>&1 || true
    curl -s --max-time 3 http://8.8.8.8/ >/dev/null 2>&1 || true
    curl -sk --max-time 3 https://8.8.8.8/ >/dev/null 2>&1 || true
    iperf3 -c 8.8.8.8 -t 3 -p 5201 --connect-timeout 2000 >/dev/null 2>&1 || true
    sleep 15
  done
}

generate_traffic &

sleep infinity
