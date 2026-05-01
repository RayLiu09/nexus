#!/usr/bin/env bash
set -Eeuo pipefail

host="${PGHOST:-127.0.0.1}"
port="${PGPORT:-5432}"
user="${PGUSER:-postgres}"
timeout="${PGCONNECT_TIMEOUT:-3}"

PGCONNECT_TIMEOUT="${timeout}" pg_isready -h "${host}" -p "${port}" -U "${user}" -q
