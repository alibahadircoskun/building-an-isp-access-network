#!/usr/bin/env bash
set -euo pipefail

. /startup/ssh-common.sh

setup_sshd_debian

exec docker-entrypoint.sh mongod --bind_ip_all
