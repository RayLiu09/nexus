#!/usr/bin/env bash
set -Eeuo pipefail

scheme="${ES_HEALTH_SCHEME:-https}"
host="${ES_HEALTH_HOST:-127.0.0.1}"
port="${ES_HEALTH_PORT:-9200}"
timeout="${ES_HEALTH_TIMEOUT:-3}"
cacert="${ES_CACERT:-/etc/elasticsearch/tls/ca.crt}"
password="${ES_PASSWORD:-}"

if [[ -z "${password}" && -n "${ES_PASSWORD_FILE:-}" && -f "${ES_PASSWORD_FILE}" ]]; then
  password="$(<"${ES_PASSWORD_FILE}")"
fi

curl_args=( -fsS --max-time "${timeout}" )
if [[ "${scheme}" == "https" && -f "${cacert}" ]]; then
  curl_args+=( --cacert "${cacert}" )
fi
if [[ -n "${ES_USERNAME:-}" && -n "${password}" ]]; then
  curl_args+=( -u "${ES_USERNAME}:${password}" )
fi

status="$(curl "${curl_args[@]}" "${scheme}://${host}:${port}/_cluster/health?local=true" | sed -n 's/.*"status":"\([^"]*\)".*/\1/p')"
[[ "${status}" == "green" || "${status}" == "yellow" ]]
