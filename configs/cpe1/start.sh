#!/usr/bin/env sh
set -eu

export CPE_PPP_USERNAME="cpe1@isp.lab"
export CPE_PPP_PASSWORD="test"
export CPE_LAN_ADDRESS="192.168.1.1/24"
export CWMP_SERIAL="CLAB-CPE-1"
export CWMP_PRODUCT_CLASS="ContainerCPE"
export CWMP_CONNECTION_REQUEST_USERNAME="cwmp"
export CWMP_CONNECTION_REQUEST_PASSWORD="cwmp-cpe1"

exec sh /startup/cpe-common.sh
