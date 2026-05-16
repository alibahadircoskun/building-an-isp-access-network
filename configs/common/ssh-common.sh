#!/usr/bin/env sh
set -eu

: "${LAB_SSH_PASSWORD:=labpass}"
: "${LAB_SSH_ADMIN_USER:=admin}"

setup_admin_user_alpine() {
  if ! id "${LAB_SSH_ADMIN_USER}" >/dev/null 2>&1; then
    adduser -D -s /bin/sh "${LAB_SSH_ADMIN_USER}"
  fi
  echo "${LAB_SSH_ADMIN_USER}:${LAB_SSH_PASSWORD}" | chpasswd
  if getent group frr >/dev/null 2>&1; then
    addgroup "${LAB_SSH_ADMIN_USER}" frr || true
  fi
  if getent group frrvty >/dev/null 2>&1; then
    addgroup "${LAB_SSH_ADMIN_USER}" frrvty || true
  fi
}

setup_admin_user_debian() {
  if ! id "${LAB_SSH_ADMIN_USER}" >/dev/null 2>&1; then
    useradd -m -s /bin/bash "${LAB_SSH_ADMIN_USER}"
  fi
  echo "${LAB_SSH_ADMIN_USER}:${LAB_SSH_PASSWORD}" | chpasswd
  if getent group frr >/dev/null 2>&1; then
    usermod -aG frr "${LAB_SSH_ADMIN_USER}" || true
  fi
  if getent group frrvty >/dev/null 2>&1; then
    usermod -aG frrvty "${LAB_SSH_ADMIN_USER}" || true
  fi
}

setup_sshd_alpine() {
  apk add --no-cache openssh sudo
  mkdir -p /root/.ssh /run/sshd
  setup_admin_user_alpine
  echo "root:${LAB_SSH_PASSWORD}" | chpasswd
  install -d -m 0755 /etc/sudoers.d
  cat > /etc/sudoers.d/90-lab-admin <<EOF
${LAB_SSH_ADMIN_USER} ALL=(ALL) NOPASSWD: ALL
EOF
  chmod 0440 /etc/sudoers.d/90-lab-admin
  ssh-keygen -A
  cat > /etc/ssh/sshd_config <<'EOF'
Port 22
Protocol 2
PermitRootLogin yes
PasswordAuthentication yes
KbdInteractiveAuthentication no
ChallengeResponseAuthentication no
PermitEmptyPasswords no
PrintMotd no
Subsystem sftp /usr/lib/ssh/sftp-server
PidFile /run/sshd.pid
EOF
  /usr/sbin/sshd
}

setup_sshd_debian() {
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y --no-install-recommends openssh-server sudo
  mkdir -p /run/sshd /root/.ssh
  setup_admin_user_debian
  echo "root:${LAB_SSH_PASSWORD}" | chpasswd
  install -d -m 0755 /etc/sudoers.d
  cat > /etc/sudoers.d/90-lab-admin <<EOF
${LAB_SSH_ADMIN_USER} ALL=(ALL) NOPASSWD: ALL
EOF
  chmod 0440 /etc/sudoers.d/90-lab-admin
  ssh-keygen -A
  cat > /etc/ssh/sshd_config <<'EOF'
Port 22
Protocol 2
PermitRootLogin yes
PasswordAuthentication yes
KbdInteractiveAuthentication no
ChallengeResponseAuthentication no
UsePAM yes
PermitEmptyPasswords no
PrintMotd no
Subsystem sftp /usr/lib/openssh/sftp-server
PidFile /run/sshd.pid
EOF
  /usr/sbin/sshd
}
