#!/usr/bin/env sh
set -eu

. /startup/ssh-common.sh

setup_sshd_alpine

exec /usr/lib/frr/docker-start
