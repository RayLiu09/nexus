#!/usr/bin/env bash
set -euo pipefail

API_BASE_URL="${NEXUS_API_BASE_URL:-http://127.0.0.1:8000}"
CONSOLE_BASE_URL="${NEXUS_CONSOLE_BASE_URL:-http://127.0.0.1:3000}"
RUN_ID="${NEXUS_E2E_RUN_ID:-$(date +%Y%m%d%H%M%S)}"

post_json() {
  local path="$1"
  local payload="$2"
  curl -fsS \
    -H "content-type: application/json" \
    -X POST \
    --data "$payload" \
    "${API_BASE_URL}${path}"
}

get_json() {
  local path="$1"
  curl -fsS "${API_BASE_URL}${path}"
}

json_field() {
  local field="$1"
  python3 -c "import json,sys; print(json.load(sys.stdin)['data']['${field}'])"
}

list_first_field() {
  local field="$1"
  python3 -c "import json,sys; data=json.load(sys.stdin)['data']; print(data[0]['${field}'] if data else '')"
}

contains() {
  local url="$1"
  local pattern="$2"
  curl -fsS "$url" | grep -q "$pattern"
}

echo "API: ${API_BASE_URL}"
echo "Console: ${CONSOLE_BASE_URL}"
echo "Run: ${RUN_ID}"

get_json "/v1/health" >/dev/null
get_json "/v1/runtime/state" >/dev/null

ORG_CODE="E2E-${RUN_ID}"
USER_NAME="e2e-admin-${RUN_ID}"
CALLER_KEY="e2e-caller-${RUN_ID}"
SOURCE_CODE="e2e-upload-${RUN_ID}"
IDEMPOTENCY_KEY="e2e-file-${RUN_ID}"

ORG_ID="$(
  post_json "/v1/org-units" \
    "{\"code\":\"${ORG_CODE}\",\"name\":\"Console E2E Org ${RUN_ID}\"}" |
    json_field id
)"

USER_ID="$(
  post_json "/v1/users" \
    "{\"username\":\"${USER_NAME}\",\"display_name\":\"Console E2E Admin\",\"role\":\"platform_data_admin\",\"org_unit_id\":\"${ORG_ID}\"}" |
    json_field id
)"

post_json "/v1/api-callers" \
  "{\"caller_key\":\"${CALLER_KEY}\",\"name\":\"Console E2E Caller\",\"org_scope\":[\"${ORG_ID}\"],\"permission_scope\":[\"asset:read\"],\"owner_user_id\":\"${USER_ID}\"}" >/dev/null

SOURCE_ID="$(
  post_json "/v1/data-sources" \
    "{\"code\":\"${SOURCE_CODE}\",\"name\":\"Console E2E Upload ${RUN_ID}\",\"source_type\":\"file_upload\",\"owner_user_id\":\"${USER_ID}\",\"org_scope_hint\":[\"${ORG_ID}\"],\"default_governance_hints\":{\"domain\":\"D4\",\"level\":\"L2\"}}" |
    json_field id
)"

CONTENT_BASE64="$(
  printf '{"id":"console-e2e-%s","title":"Console E2E %s","body":"NEXUS console live API E2E sample"}' "$RUN_ID" "$RUN_ID" | base64 -w 0
)"

INGEST_RESPONSE="$(
  post_json "/v1/ingest/files" \
    "{\"data_source_id\":\"${SOURCE_ID}\",\"idempotency_key\":\"${IDEMPOTENCY_KEY}\",\"filename\":\"console-e2e-${RUN_ID}.json\",\"content_type\":\"application/json\",\"content_base64\":\"${CONTENT_BASE64}\",\"submitted_by_user_id\":\"${USER_ID}\",\"process_now\":true}"
)"

BATCH_ID="$(printf '%s' "$INGEST_RESPONSE" | python3 -c "import json,sys; print(json.load(sys.stdin)['data']['batch']['id'])")"
RAW_ID="$(printf '%s' "$INGEST_RESPONSE" | python3 -c "import json,sys; print(json.load(sys.stdin)['data']['raw_object']['id'])")"
JOB_ID="$(printf '%s' "$INGEST_RESPONSE" | python3 -c "import json,sys; print(json.load(sys.stdin)['data']['job']['id'])")"
ASSET_ID="$(printf '%s' "$INGEST_RESPONSE" | python3 -c "import json,sys; print(json.load(sys.stdin)['data']['asset']['id'])")"
REF_ID="$(printf '%s' "$INGEST_RESPONSE" | python3 -c "import json,sys; print(json.load(sys.stdin)['data']['normalized_ref']['id'])")"

get_json "/v1/ingest/batches/${BATCH_ID}/raw-objects" | list_first_field id | grep -q "$RAW_ID"
get_json "/v1/jobs/${JOB_ID}/stages" | grep -q "assetize"
get_json "/v1/assets/${ASSET_ID}" | grep -q "$REF_ID"
get_json "/v1/audit-logs" | grep -q "IngestBatchSubmitted"

contains "${CONSOLE_BASE_URL}/workbench" "真实 API 已连接"
contains "${CONSOLE_BASE_URL}/data-sources" "${SOURCE_CODE}"
contains "${CONSOLE_BASE_URL}/raw-ledger" "$(printf '%s' "$RAW_ID" | cut -c1-8)"
contains "${CONSOLE_BASE_URL}/jobs" "$(printf '%s' "$JOB_ID" | cut -c1-8)"
contains "${CONSOLE_BASE_URL}/assets" "console-e2e-${RUN_ID}.json"
contains "${CONSOLE_BASE_URL}/assets/${ASSET_ID}" "$(printf '%s' "$REF_ID" | cut -c1-8)"
contains "${CONSOLE_BASE_URL}/iam-audit" "IngestBatchSubmitted"

echo "PASS week2 console API E2E"
echo "batch=${BATCH_ID}"
echo "raw_object=${RAW_ID}"
echo "job=${JOB_ID}"
echo "asset=${ASSET_ID}"
echo "normalized_ref=${REF_ID}"
