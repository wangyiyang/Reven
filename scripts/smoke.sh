#!/usr/bin/env bash
set -euo pipefail

readonly BASE_URL="${REVEN_BASE_URL:-http://localhost:8080}"
readonly AUTHORITY="${BASE_URL#*://}"
readonly HOST_PORT="${AUTHORITY%%/*}"
readonly HOST="${HOST_PORT%%:*}"

if [[ "${BASE_URL}" != http://* ]]; then
  echo "REVEN_BASE_URL must use HTTP" >&2
  exit 2
fi
if [[ "${HOST_PORT}" == *"@"* ]] || [[ -z "${HOST}" ]]; then
  echo "REVEN_BASE_URL must not contain credentials" >&2
  exit 2
fi

set +x
curl --fail --silent --show-error \
  --request GET \
  --connect-timeout 5 \
  --max-time 15 \
  "${BASE_URL%/}/api/health" |
  grep --fixed-strings '"status":"ok"'
