#!/usr/bin/env bash
set -Eeuo pipefail

host="${REDIS_HOST:-127.0.0.1}"
port="${REDIS_PORT:-6379}"
timeout="${REDIS_TIMEOUT:-3}"
password="${REDIS_PASSWORD:-}"

if [[ -z "${password}" && -n "${REDIS_PASSWORD_FILE:-}" && -f "${REDIS_PASSWORD_FILE}" ]]; then
  password="$(<"${REDIS_PASSWORD_FILE}")"
fi

args=( -h "${host}" -p "${port}" --no-auth-warning )
if [[ -n "${password}" ]]; then
  args+=( -a "${password}" )
fi

redis-cli "${args[@]}" --raw PING | grep -qx "PONG"
