#!/usr/bin/env bash
# BNG demo helper — run during the video to show live subscriber state.
# Usage: bash /usr/local/bin/show-bng

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║              BNG Live Subscriber Sessions                    ║"
echo "╚══════════════════════════════════════════════════════════════╝"
accel-cmd show sessions 2>/dev/null || echo "(accel-pppd not running)"

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║                   BNG Statistics                            ║"
echo "╚══════════════════════════════════════════════════════════════╝"
accel-cmd show stat 2>/dev/null || true

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║             OSPF Neighbors  (BNG ↔ Core)                   ║"
echo "╚══════════════════════════════════════════════════════════════╝"
vtysh -c 'show ip ospf neighbor' 2>/dev/null || true

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║           OSPF Routes (subscriber pool advertisement)       ║"
echo "╚══════════════════════════════════════════════════════════════╝"
vtysh -c 'show ip route ospf' 2>/dev/null || true

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║     Subscriber Policy Routing Table (table 200)             ║"
echo "╚══════════════════════════════════════════════════════════════╝"
ip route show table 200 2>/dev/null || true

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║          Active PPP Interfaces                               ║"
echo "╚══════════════════════════════════════════════════════════════╝"
ip -br addr show | grep ppp || echo "(no PPP sessions)"
