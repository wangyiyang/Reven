#!/usr/bin/env bash
set -euo pipefail

readonly BASE_URL="${REVEN_BASE_URL:-https://dev.wangyiyang.cc}"
readonly AUTH_USER="${REVEN_BASIC_AUTH_USER:?REVEN_BASIC_AUTH_USER is required}"
readonly AUTH_PASSWORD="${REVEN_BASIC_AUTH_PASSWORD:?REVEN_BASIC_AUTH_PASSWORD is required}"

if [[ "${BASE_URL}" != https://* ]] && [[ "${REVEN_ALLOW_HTTP_LOCALHOST:-}" != "1" ]]; then
  echo "REVEN_BASE_URL must use HTTPS" >&2
  exit 2
fi
if [[ "${BASE_URL}" == http://* ]] && [[ ! "${BASE_URL}" =~ ^http://(localhost|127\.0\.0\.1)(:[0-9]+)?$ ]]; then
  echo "HTTP exception is restricted to localhost" >&2
  exit 2
fi

curl --fail --silent --show-error \
  --connect-timeout 5 \
  --max-time 15 \
  --user "${AUTH_USER}:${AUTH_PASSWORD}" \
  "${BASE_URL%/}/api/health" |
  grep --fixed-strings '"status":"ok"'
