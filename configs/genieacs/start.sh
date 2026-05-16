#!/usr/bin/env bash
set -euo pipefail

. /startup/ssh-common.sh

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends ca-certificates curl iputils-ping jq netcat-openbsd

npm install -g genieacs@1.2.16

setup_sshd_debian

until nc -z mongo 27017; do
  echo "waiting for mongo..."
  sleep 2
done

if [[ -z "${GENIEACS_UI_JWT_SECRET:-}" ]]; then
  echo "GENIEACS_UI_JWT_SECRET is required"
  exit 1
fi

export GENIEACS_CONNECTION_REQUEST_ALLOW_BASIC_AUTH=true

mkdir -p /var/log/genieacs

export GENIEACS_CWMP_ACCESS_LOG_FILE=/var/log/genieacs/cwmp-access.log
export GENIEACS_NBI_ACCESS_LOG_FILE=/var/log/genieacs/nbi-access.log
export GENIEACS_FS_ACCESS_LOG_FILE=/var/log/genieacs/fs-access.log
export GENIEACS_UI_ACCESS_LOG_FILE=/var/log/genieacs/ui-access.log

(genieacs-cwmp) &
(genieacs-nbi) &
(genieacs-fs) &
(genieacs-ui) &

# Wait for NBI to accept connections before loading provisioning data.
until curl -sf http://localhost:7557/devices >/dev/null 2>&1; do
  echo "waiting for genieacs-nbi..."
  sleep 3
done

# Load provisions, presets, and firmware via Python so multi-line JavaScript
# strings are always valid JSON (json.dumps handles newline/quote escaping).
# curl -d with shell here-docs embeds literal newlines which are invalid JSON.
python3 << 'PYEOF'
import json, subprocess, os, struct

NBI = "http://localhost:7557"

def nbi_put(path, body):
    data = json.dumps(body) if not isinstance(body, (bytes, bytearray)) else body
    r = subprocess.run(
        ["curl", "-sf", "-X", "PUT", f"{NBI}{path}",
         "-H", "Content-Type: application/json", "-d", data],
        capture_output=True)
    status = "ok" if r.returncode == 0 else f"FAILED (curl {r.returncode})"
    print(f"  PUT {path}: {status}")
    return r.returncode == 0

def nbi_put_binary(path, data, headers):
    args = ["curl", "-sf", "-X", "PUT", f"{NBI}{path}", "--data-binary", "@-"]
    for k, v in headers.items():
        args += ["-H", f"{k}: {v}"]
    r = subprocess.run(args, input=data, capture_output=True)
    status = "ok" if r.returncode == 0 else f"FAILED (curl {r.returncode})"
    print(f"  PUT {path}: {status}")
    return r.returncode == 0

print("Loading provisions...")
nbi_put("/provisions/bootstrap", """
// Zero-touch provisioning: configure management and collect device inventory
declare("Device.ManagementServer.PeriodicInformEnable",   {value: 1}, {value: [true,  "xsd:boolean"]});
declare("Device.ManagementServer.PeriodicInformInterval", {value: 1}, {value: [60,    "xsd:unsignedInt"]});
declare("Device.DeviceInfo.Manufacturer",     {value: 1});
declare("Device.DeviceInfo.SerialNumber",     {value: 1});
declare("Device.DeviceInfo.SoftwareVersion",  {value: 1});
declare("Device.DeviceInfo.HardwareVersion",  {value: 1});
declare("Device.DeviceInfo.UpTime",           {value: 1});
declare("Device.WANDevice.1.WANConnectionDevice.1.WANPPPConnection.1.ExternalIPAddress", {value: 1});
declare("Device.WANDevice.1.WANConnectionDevice.1.WANPPPConnection.1.Username",          {value: 1});
declare("Device.LANDevice.1.WLANConfiguration.1.SSID",    {value: 1});
declare("Device.LANDevice.1.WLANConfiguration.1.Channel", {value: 1});
declare("Device.LANDevice.1.Hosts.HostNumberOfEntries",   {value: 1});
""")

nbi_put("/provisions/boot", """
// Refresh live state that changes across reboots
declare("Device.DeviceInfo.SoftwareVersion",  {value: 1});
declare("Device.DeviceInfo.UpTime",           {value: 1});
declare("Device.WANDevice.1.WANConnectionDevice.1.WANPPPConnection.1.ExternalIPAddress", {value: 1});
""")

print("Loading presets...")
nbi_put("/presets/bootstrap", {
    "weight": 100, "precondition": "true",
    "events": {"0 BOOTSTRAP": True},
    "configurations": [{"type": "provision", "name": "bootstrap", "args": []}]
})
nbi_put("/presets/boot", {
    "weight": 90, "precondition": "true",
    "events": {"1 BOOT": True},
    "configurations": [{"type": "provision", "name": "boot", "args": []}]
})

print("Uploading firmware file...")
header  = b"CLAB-FW\x00" + struct.pack(">I", 2) + b"ContainerCPE\x00" * 5
payload = header + os.urandom(8192)
nbi_put_binary("/files/firmware-v2.0.bin", payload, {
    "Content-Type": "application/octet-stream",
    "fileType":     "1 Firmware Upgrade Image",
    "oui":          "AC1AB2",
    "productClass": "ContainerCPE",
    "version":      "2.0",
})
print("GenieACS provisioning data loaded.")
PYEOF

wait
