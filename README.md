# ISP Access Network Lab

A containerlab-based simulation of a broadband access network. It puts PPPoE subscriber access, Deep Packet Inspection, and TR-069 remote management together in one topology you can actually run and follow.

```
                          ┌─────────────┐
                          │   upstream  │ AS 65000
                          │  (8.8.8.8)  │
                          └──────┬──────┘
                        eBGP     │ eth1
                          ┌──────┴──────┐
                          │    core     │ AS 65001
                          │ BGP + OSPF  │
                          └──────┬──────┘
                        OSPF     │ eth2
                          ┌──────┴──────┐
                          │     bng     │ accel-ppp (PPPoE)
                          │             │ FRR (OSPF)
                          └──────┬──────┘
                        PPPoE    │ eth2
                          ┌──────┴──────┐
                          │     dpi     │ Linux bridge
                          │  (ntopng)   │ eth1 ↔ eth2/eth3
                          └──────┬──────┘
                    ┌────────────┴────────────┐
               eth2 │                    eth3 │
            ┌───────┴──────┐       ┌──────────┴───┐
            │    cpe-1     │       │    cpe-2     │
            │  pppoe+CWMP  │       │  pppoe+CWMP  │
            └──────┬───────┘       └──────┬───────┘
              eth2 │                 eth2 │
            ┌──────┴───────┐       ┌──────┴───────┐
            │    sub-1     │       │    sub-2     │
            │ 192.168.1.2  │       │ 192.168.2.2  │
            └──────────────┘       └──────────────┘

            GenieACS (ACS) ←──────── TR-069 / CWMP
            MongoDB        ←──────── (via BNG DNAT)
```

---

## What this lab covers

- **PPPoE / BNG** — subscribers come online through accel-ppp running on the BNG node. Each CPE discovers the access concentrator, negotiates a PPP session, gets a 100.64.0.x address, and NATs its LAN behind it.
- **Routing** — the BNG advertises the subscriber pool into OSPF. The core node runs eBGP toward upstream and OSPF toward the BNG. The upstream node holds the lab's "internet" (8.8.8.8/32).
- **DPI** — the DPI node is an inline Linux bridge with ntopng and nDPI watching all flows. Traffic from both subscriber nodes crosses it, including the CWMP management traffic from the CPEs.
- **ACS / TR-069** — each CPE runs a Python CWMP client that sends Inform messages to GenieACS on boot and periodically. GenieACS collects parameters and can push RPCs back to the device: `SetParameterValues`, `Download`, `Reboot`, `FactoryReset`.

---

## Requirements

- [containerlab](https://containerlab.dev) v0.57 or later
- Docker

No pre-built images. Every node pulls a public base image and configures itself at startup.

---

## Deploy

```bash
cd topology
clab deploy -t isp-dpi-acs.clab.yml
```

**First-boot warning:** the BNG builds accel-ppp from source. This takes 8–12 minutes depending on your machine. Subsequent deploys reuse the compiled binary if the container is not destroyed.

Watch BNG readiness:

```bash
docker logs -f clab-isp-dpi-acs-bng
```

When you see `accel-pppd started`, the BNG is ready. The CPEs will bring up PPPoE sessions automatically once it is.

To tear down:

```bash
cd topology
clab destroy -t isp-dpi-acs.clab.yml
```

---

## Management

### Node addresses

| Node      | Mgmt IP       | Role                             |
|-----------|---------------|----------------------------------|
| upstream  | 172.31.255.2  | BGP AS 65000, advertises 8.8.8.8 |
| core      | 172.31.255.4  | BGP AS 65001 + OSPF hub          |
| bng       | 172.31.255.3  | PPPoE BNG (accel-ppp) + OSPF     |
| dpi       | 172.31.255.5  | ntopng transparent bridge        |
| genieacs  | 172.31.255.8  | TR-069 ACS                       |
| mongo     | 172.31.255.6  | MongoDB for GenieACS             |
| cpe-1     | 172.31.255.22 | CPE 1 — PPPoE cpe1@isp.lab       |
| cpe-2     | 172.31.255.23 | CPE 2 — PPPoE cpe2@isp.lab       |
| sub-1     | 172.31.255.7  | Subscriber behind cpe-1          |
| sub-2     | 172.31.255.9  | Subscriber behind cpe-2          |

SSH is available on all nodes. Username `admin`, password `labpass`.

### Web UIs

| Service  | URL                    |
|----------|------------------------|
| GenieACS | http://localhost:20030 |
| ntopng   | http://localhost:20031 |

---

## Exploring the lab

### PPPoE sessions on the BNG

SSH to the BNG and run the bundled helper:

```bash
ssh admin@172.31.255.3
show-bng
```

This prints the active PPPoE session table, BNG statistics, OSPF neighbors, OSPF routes, the subscriber policy routing table (table 200), and active PPP interfaces.

### Verify connectivity from a subscriber

```bash
docker exec clab-isp-dpi-acs-sub-1 ping -c 4 8.8.8.8
```

The path: sub-1 → CPE-1 NAT → ppp0 → DPI bridge → BNG → OSPF → core → BGP → upstream (8.8.8.8).

### Check a CPE's PPP address and default route

```bash
docker exec clab-isp-dpi-acs-cpe-1 ip addr show ppp0
docker exec clab-isp-dpi-acs-cpe-1 ip route
```

### DPI — live flows

Open http://localhost:20031 and go to **Flows**. sub-1 and sub-2 generate traffic continuously: ICMP, DNS, HTTP, TLS, and iperf3. ntopng classifies them using nDPI.

The CWMP traffic from the CPEs also crosses the DPI bridge (TCP 7547), so you can see management and subscriber flows in the same view.

### GenieACS — device inventory

Open http://localhost:20030. Both CPEs should appear after they boot and send their first Inform.

Click into a device to see the parameters GenieACS collected: manufacturer, serial, software version, WAN IP, SSID, channel, uptime.

### Push a parameter change via the API

Change the Wi-Fi SSID on CPE-1:

```bash
curl -s -X POST \
  "http://localhost:20057/devices/AC1AB2-ContainerCPE-CLAB%252DCPE%252D1/tasks?connection_request" \
  -H "Content-Type: application/json" \
  -d '{"name":"setParameterValues","parameterValues":[["Device.LANDevice.1.WLANConfiguration.1.SSID","NewSSID","xsd:string"]]}' \
  | python3 -m json.tool
```

The `?connection_request` parameter tells GenieACS to wake the CPE immediately instead of waiting for the next periodic Inform. Watch the CPE apply the change:

```bash
docker exec clab-isp-dpi-acs-cpe-1 tail -f /var/log/cwmp-client.log
```

### Trigger a firmware download

```bash
curl -s -X POST \
  "http://localhost:20057/devices/AC1AB2-ContainerCPE-CLAB%252DCPE%252D1/tasks?connection_request" \
  -H "Content-Type: application/json" \
  -d '{"name":"download","file":"firmware-v2.0.bin"}' \
  | python3 -m json.tool
```

The firmware file is pre-loaded into GenieACS at startup. The CPE fetches it from the GenieACS file server and logs the result.

---

## Credentials

| Service              | Username     | Password   |
|----------------------|--------------|------------|
| SSH (all nodes)      | admin        | labpass     |
| PPPoE — cpe-1        | cpe1@isp.lab | test        |
| PPPoE — cpe-2        | cpe2@isp.lab | test        |
| CWMP conn-req cpe-1  | cwmp         | cwmp-cpe1   |
| CWMP conn-req cpe-2  | cwmp         | cwmp-cpe2   |

---

## CWMP traffic path

CPEs are configured to reach the ACS at `http://100.64.0.1:7547/` — the BNG's subscriber-side address. This routes CWMP through the DPI bridge so ntopng can see it alongside subscriber data.

The BNG DNATs that address and port to the actual GenieACS container at `172.31.255.8:7547`.

```
CPE ppp0 → 100.64.0.1:7547 (BNG)
  → iptables DNAT → 172.31.255.8:7547 (genieacs-cwmp)
  → GenieACS sends Inform response + pending tasks
  → CPE applies RPCs and responds
```

---

## Repo structure

```
topology/          containerlab topology file and drawio diagram
configs/
  bng/             accel-ppp config, FRR config, startup script, show-bng helper
  core/            FRR config and startup script
  upstream/        FRR config and startup script
  dpi/             ntopng config and startup script
  cpe1/ cpe2/      per-CPE environment (PPPoE credentials, CWMP serial)
  common/          shared scripts: SSH setup, CPE init, CWMP client
  genieacs/        GenieACS startup + provisioning loader
  mongo/           MongoDB startup script
  sub1/ sub2/      subscriber startup + traffic generation
```
