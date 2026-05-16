#!/usr/bin/env sh
set -eu

export CPE_PPP_USERNAME="cpe2@isp.lab"
export CPE_PPP_PASSWORD="test"
export CPE_LAN_ADDRESS="192.168.2.1/24"
export CWMP_SERIAL="CLAB-CPE-2"
export CWMP_PRODUCT_CLASS="ContainerCPE"
export CWMP_CONNECTION_REQUEST_USERNAME="cwmp"
export CWMP_CONNECTION_REQUEST_PASSWORD="cwmp-cpe2"

exec sh /startup/cpe-common.sh
