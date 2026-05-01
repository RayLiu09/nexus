#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $# -lt 2 ]]; then
  echo "usage: $0 <supervisor-program-name> <healthcheck-command> [args...]" >&2
  exit 64
fi

program_name="$1"
shift

check_interval="${CHECK_INTERVAL:-30}"
max_failures="${MAX_FAILURES:-3}"
restart_cooldown="${RESTART_COOLDOWN:-120}"
supervisor_conf="${SUPERVISOR_CONF:-/etc/supervisor/supervisord.conf}"

failures=0

while true; do
  if "$@"; then
    failures=0
  else
    failures=$((failures + 1))
    echo "$(date -Is) healthcheck failed for ${program_name}, failures=${failures}/${max_failures}" >&2
  fi

  if [[ "${failures}" -ge "${max_failures}" ]]; then
    echo "$(date -Is) restarting ${program_name} through supervisorctl" >&2
    supervisorctl -c "${supervisor_conf}" restart "${program_name}" || true
    failures=0
    sleep "${restart_cooldown}"
  fi

  sleep "${check_interval}"
done
