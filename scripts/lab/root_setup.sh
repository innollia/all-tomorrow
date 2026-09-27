#!/usr/bin/env bash
# One-time root setup for the all-tomorrow live lab inside WSL Ubuntu.
set -euo pipefail
service postgresql start >/dev/null
su postgres -c "psql -tAc \"SELECT 1 FROM pg_roles WHERE rolname='fixme'\"" | grep -q 1 || su postgres -c "createuser -s fixme"
for d in at_dbos_probe at_external_fixture at_semantic_test; do
  su postgres -c "psql -tAc \"SELECT 1 FROM pg_database WHERE datname='$d'\"" | grep -q 1 || su postgres -c "createdb -O fixme $d"
done
mkdir -p /opt/restate/1.7.10
cd /opt/restate/1.7.10
if [ ! -d restate-server-x86_64-unknown-linux-musl ]; then
  curl -fsSL -o r.tar.xz https://github.com/restatedev/restate/releases/download/v1.7.10/restate-server-x86_64-unknown-linux-musl.tar.xz
  tar xf r.tar.xz
fi
ls /opt/restate/1.7.10/restate-server-x86_64-unknown-linux-musl
chown -R fixme:fixme /opt
echo ROOT_SETUP_OK
