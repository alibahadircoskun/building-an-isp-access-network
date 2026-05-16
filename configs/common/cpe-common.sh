#!/usr/bin/env sh
set -eu

. /startup/ssh-common.sh

: "${CPE_PPP_USERNAME:?CPE_PPP_USERNAME is required}"
: "${CPE_PPP_PASSWORD:=test}"
: "${CPE_LAN_ADDRESS:?CPE_LAN_ADDRESS is required}"
: "${CPE_ACS_URL:=http://100.64.0.1:7547/}"
export CPE_ACS_URL
: "${CPE_PERIODIC_INFORM_INTERVAL:=60}"
export CPE_PERIODIC_INFORM_INTERVAL

apk add --no-cache \
  ca-certificates \
  curl \
  iproute2 \
  iptables \
  ppp \
  python3 \
  rp-pppoe \
  tcpdump

setup_sshd_alpine

for ifn in eth1 eth2; do
  for _ in $(seq 1 120); do
    if ip link show "$ifn" >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
done

ip link set eth1 up
ip link set eth2 up

# Wait for BNG Access Concentrator to respond to PPPoE discovery before
# starting pppd — avoids exponential back-off delays on first lab boot.
echo "Waiting for BNG AC on eth1..."
until pppoe-discovery -I eth1 2>/dev/null | grep -qiE "AC-Name|Access-Concentrator"; do
  sleep 3
done
echo "BNG AC ready"
ip addr replace "${CPE_LAN_ADDRESS}" dev eth2

sysctl -w net.ipv4.ip_forward=1 >/dev/null
iptables -t nat -C POSTROUTING -o ppp+ -j MASQUERADE 2>/dev/null || iptables -t nat -A POSTROUTING -o ppp+ -j MASQUERADE
iptables -C FORWARD -i eth2 -o ppp+ -j ACCEPT 2>/dev/null || iptables -A FORWARD -i eth2 -o ppp+ -j ACCEPT
iptables -C FORWARD -i ppp+ -o eth2 -m state --state ESTABLISHED,RELATED -j ACCEPT 2>/dev/null || iptables -A FORWARD -i ppp+ -o eth2 -m state --state ESTABLISHED,RELATED -j ACCEPT

mkdir -p /etc/ppp/peers /var/lib/cwmp-client /var/log

cat > /etc/ppp/chap-secrets <<EOF
"${CPE_PPP_USERNAME}" * "${CPE_PPP_PASSWORD}"
EOF

cat > /etc/ppp/peers/wan <<EOF
plugin pppoe.so eth1
user "${CPE_PPP_USERNAME}"
password "${CPE_PPP_PASSWORD}"
noauth
defaultroute
replacedefaultroute
usepeerdns
persist
maxfail 0
lcp-echo-interval 5
lcp-echo-failure 3
mtu 1492
mru 1492
hide-password
logfile /var/log/ppp-wan.log
EOF

pppd call wan &

for _ in $(seq 1 60); do
  if ip link show ppp0 >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

python3 /startup/cwmp-client.py >>/var/log/cwmp-client.log 2>&1 &

sleep infinity
