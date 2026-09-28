#!/bin/sh
# Start as root only long enough to make the data volume ours (Railway and
# other hosts mount volumes owned by root), then drop to the camena user.
set -e
DATA="${CAMENA_DATA_DIR:-/data}"
mkdir -p "$DATA/home"
if [ "$(id -u)" = "0" ]; then
  chown -R camena:camena "$DATA"
  exec setpriv --reuid=camena --regid=camena --init-groups "$0" "$@"
fi
exec uvicorn app.main:app_factory --factory --host 0.0.0.0 --port "${PORT:-8000}" \
  --proxy-headers --forwarded-allow-ips '*'
