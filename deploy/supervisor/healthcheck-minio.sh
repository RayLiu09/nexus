#!/usr/bin/env bash
set -Eeuo pipefail

scheme="${MINIO_HEALTH_SCHEME:-http}"
host="${MINIO_HEALTH_HOST:-127.0.0.1}"
port="${MINIO_HEALTH_PORT:-9000}"
timeout="${MINIO_HEALTH_TIMEOUT:-3}"

curl -fsS --max-time "${timeout}" "${scheme}://${host}:${port}/minio/health/live" >/dev/null
