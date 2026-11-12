#!/bin/sh
# Copy SSH keys/config mounted read-only at /ssh-src into /root/.ssh with
# root ownership and strict permissions (ssh refuses configs owned by other users).
set -e
if [ -d /ssh-src ] && [ "$(ls -A /ssh-src 2>/dev/null)" ]; then
  mkdir -p /root/.ssh
  cp -a /ssh-src/. /root/.ssh/
  chown -R root:root /root/.ssh
  chmod 700 /root/.ssh
  find /root/.ssh -type f -exec chmod 600 {} \;
  find /root/.ssh -type f -name '*.pub' -exec chmod 644 {} \;
fi
exec "$@"
