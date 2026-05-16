#!/usr/bin/env bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

. /startup/ssh-common.sh

apt-get update
apt-get -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold" install -y --no-install-recommends \
  ca-certificates curl iproute2 iputils-ping iptables \
  ppp pppoe frr git build-essential cmake pkg-config libssl-dev libpcre2-dev

setup_sshd_debian

cat > /etc/ppp/chap-secrets <<'EOF'
# client        server   secret   ip-address
cpe1@isp.lab    *        test     *
cpe2@isp.lab    *        test     *
EOF
chmod 600 /etc/ppp/chap-secrets

if ! command -v accel-pppd >/dev/null 2>&1; then
  cd /tmp
  rm -rf accel-ppp
  git clone --depth 1 https://github.com/accel-ppp/accel-ppp.git
  cd accel-ppp
  cmake -S . -B build -DBUILD_IPOE_DRIVER=FALSE -DCPACK_TYPE=Debian
  cmake --build build -j"$(nproc)"
  cd build
  cpack -G DEB
  dpkg -i accel-ppp*.deb
fi

sysctl -w net.ipv4.ip_forward=1

# Debian installs accel-ppp modules under /usr/lib64/accel-ppp while the
# packaged binary looks under /usr/local/lib64/accel-ppp.
if [[ -d /usr/lib64/accel-ppp && ! -e /usr/local/lib64/accel-ppp ]]; then
  mkdir -p /usr/local/lib64
  ln -s /usr/lib64/accel-ppp /usr/local/lib64/accel-ppp
fi

# Wait for data-plane links to be attached by containerlab before touching eth2.
for _ in $(seq 1 120); do
  if ip link show eth2 >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

if ! ip link show eth2 >/dev/null 2>&1; then
  echo "ERROR: eth2 not present after waiting for link attach"
  exit 1
fi

ip link set eth2 up

service frr restart

# Policy routing: PPP subscriber traffic must use the data-plane path (eth1 → core),
# not the management default route (eth0). The kernel default always wins over OSPF
# in containerlab since containerlab installs it at metric 0. A separate routing table
# keyed on source address (subscriber pool) bypasses that management default cleanly.
ip route add default via 10.0.1.1 dev eth1 table 200 2>/dev/null || true
ip rule add from 100.64.0.0/24 lookup 200 priority 100 2>/dev/null || true
# Management network must be reachable from table 200 so DNAT'd CWMP packets
# (src=100.64.0.x, dst=172.31.255.8 after DNAT) route via eth0, not eth1.
ip route add 172.31.255.0/24 dev eth0 table 200 2>/dev/null || true

# CWMP via data-plane: CPEs use 100.64.0.1:7547 as ACS URL so their TR-069
# traffic traverses the DPI bridge (visible in ntopng) rather than the mgmt
# network. DNAT maps that address/port to the actual genieacs container.
iptables -t nat -A PREROUTING -i ppp+ -p tcp --dport 7547 \
  -j DNAT --to-destination 172.31.255.8:7547
iptables -t nat -A POSTROUTING -o eth0 -p tcp -d 172.31.255.8 --dport 7547 \
  -j MASQUERADE
iptables -A FORWARD -i ppp+ -o eth0 -p tcp -d 172.31.255.8 --dport 7547 -j ACCEPT
iptables -A FORWARD -i eth0 -o ppp+ -m state --state ESTABLISHED,RELATED -j ACCEPT

# accel-ppp CPack install may place libs under /usr/local/lib without
# updating linker cache inside ephemeral containers.
LIBTRITON_PATH="$(find /usr /usr/local /lib -name libtriton.so 2>/dev/null | head -n 1 || true)"
if [[ -z "${LIBTRITON_PATH}" ]]; then
  echo "ERROR: libtriton.so not found after accel-ppp installation"
  exit 1
fi
LIBTRITON_DIR="$(dirname "${LIBTRITON_PATH}")"
printf '%s\n' "${LIBTRITON_DIR}" >/etc/ld.so.conf.d/accel-ppp.conf
ldconfig || true
export LD_LIBRARY_PATH="${LIBTRITON_DIR}:${LD_LIBRARY_PATH:-}"

pkill -x accel-pppd || true
rm -f /run/accel-pppd.pid
accel-pppd -p /run/accel-pppd.pid -d -c /etc/accel-ppp.conf

exec tail -F /var/log/accel-ppp.log /var/log/frr/frr.log
