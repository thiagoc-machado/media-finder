#!/bin/sh
set -eu

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"
CONFIG_DIR="${CONFIG_DIR:-/config}"

case "${PUID}:${PGID}" in
  *[!0-9:]*|*:|:*)
    echo "PUID and PGID must be positive integers." >&2
    exit 1
    ;;
esac

if [ "${PUID}" -eq 0 ] || [ "${PGID}" -eq 0 ]; then
  echo "PUID and PGID must not be 0 because the application must run as non-root." >&2
  exit 1
fi

if [ "$(id -g mediafinder)" -ne "${PGID}" ]; then
  groupmod --gid "${PGID}" mediafinder
fi

if [ "$(id -u mediafinder)" -ne "${PUID}" ] || [ "$(id -g mediafinder)" -ne "${PGID}" ]; then
  usermod --uid "${PUID}" --gid "${PGID}" mediafinder
fi

mkdir -p "${CONFIG_DIR}"
chown -R "${PUID}:${PGID}" "${CONFIG_DIR}"

exec gosu "${PUID}:${PGID}" sh -c '
  alembic upgrade head
  exec uvicorn app.main:app \
    --host "${APP_HOST:-0.0.0.0}" \
    --port "${APP_PORT:-8091}" \
    --log-level "$(printf "%s" "${LOG_LEVEL:-INFO}" | tr "[:upper:]" "[:lower:]")"
'
