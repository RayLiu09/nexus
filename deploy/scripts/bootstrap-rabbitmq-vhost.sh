#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  deploy/scripts/bootstrap-rabbitmq-vhost.sh [env-file]

Creates or updates the NEXUS RabbitMQ vhost definitions:
  - vhost
  - nexus.jobs topic exchange
  - nexus.dlx topic exchange
  - DLX policy for nexus.* queues
  - permissions for an existing RABBITMQ_USERNAME/RABBITMQ_USER, when present

The script never creates RabbitMQ users because passwords should be provisioned
through service-native secret handling.
USAGE
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

env_file="${1:-}"
if [[ -n "${env_file}" ]]; then
  if [[ ! -f "${env_file}" ]]; then
    echo "env file not found: ${env_file}" >&2
    exit 1
  fi
  set -a
  # shellcheck disable=SC1090
  . "${env_file}"
  set +a
fi

: "${RABBITMQ_VHOST:=nexus}"
: "${RABBITMQ_EXCHANGE_JOBS:=nexus.jobs}"
: "${RABBITMQ_EXCHANGE_DLX:=nexus.dlx}"
: "${RABBITMQ_DEFAULT_QUEUE_TYPE:=quorum}"

RABBITMQ_USERNAME="${RABBITMQ_USERNAME:-${RABBITMQ_USER:-}}"

if ! command -v rabbitmqctl >/dev/null 2>&1; then
  echo "rabbitmqctl is required on the RabbitMQ host." >&2
  exit 1
fi

if [[ "${RABBITMQ_VHOST}" == /* ]]; then
  echo "warning: RABBITMQ_VHOST is '${RABBITMQ_VHOST}'." >&2
  echo "For NEXUS, use 'nexus'. In AMQP URLs, /nexus means vhost 'nexus'." >&2
fi

json_escape() {
  printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'
}

vhost_json="$(json_escape "${RABBITMQ_VHOST}")"
jobs_exchange_json="$(json_escape "${RABBITMQ_EXCHANGE_JOBS}")"
dlx_exchange_json="$(json_escape "${RABBITMQ_EXCHANGE_DLX}")"
queue_type_json="$(json_escape "${RABBITMQ_DEFAULT_QUEUE_TYPE}")"

tmp_file="$(mktemp "${TMPDIR:-/tmp}/nexus-rabbitmq-definitions.XXXXXX.json")"
trap 'rm -f "${tmp_file}"' EXIT

cat >"${tmp_file}" <<JSON
{
  "users": [],
  "vhosts": [
    {
      "name": "${vhost_json}",
      "description": "Nexus application virtual host for asynchronous jobs and dead-letter routing.",
      "metadata": {
        "description": "Nexus application virtual host. Protected from accidental deletion.",
        "tags": ["nexus", "protected"],
        "default_queue_type": "${queue_type_json}",
        "protected_from_deletion": true
      },
      "tags": ["nexus", "protected"],
      "default_queue_type": "${queue_type_json}"
    }
  ],
  "permissions": [],
  "topic_permissions": [],
  "parameters": [],
  "global_parameters": [],
  "policies": [
    {
      "vhost": "${vhost_json}",
      "name": "nexus-dlx-defaults",
      "pattern": "^nexus\\\\.",
      "apply-to": "queues",
      "definition": {
        "dead-letter-exchange": "${dlx_exchange_json}"
      },
      "priority": 0
    }
  ],
  "queues": [],
  "exchanges": [
    {
      "name": "${jobs_exchange_json}",
      "vhost": "${vhost_json}",
      "type": "topic",
      "durable": true,
      "auto_delete": false,
      "internal": false,
      "arguments": {}
    },
    {
      "name": "${dlx_exchange_json}",
      "vhost": "${vhost_json}",
      "type": "topic",
      "durable": true,
      "auto_delete": false,
      "internal": false,
      "arguments": {}
    }
  ],
  "bindings": []
}
JSON

rabbitmqctl import_definitions "${tmp_file}"

if [[ -n "${RABBITMQ_USERNAME}" ]]; then
  if rabbitmqctl list_users | awk '{print $1}' | grep -Fxq "${RABBITMQ_USERNAME}"; then
    rabbitmqctl set_permissions -p "${RABBITMQ_VHOST}" "${RABBITMQ_USERNAME}" '.*' '.*' '.*'
  else
    echo "warning: RabbitMQ user '${RABBITMQ_USERNAME}' does not exist; permissions were not changed." >&2
  fi
fi

rabbitmqctl list_exchanges -p "${RABBITMQ_VHOST}" name type durable | awk \
  -v jobs="${RABBITMQ_EXCHANGE_JOBS}" \
  -v dlx="${RABBITMQ_EXCHANGE_DLX}" '
  $1 == jobs || $1 == dlx { print }
'
