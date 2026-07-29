#!/usr/bin/env bash
set -euo pipefail

readonly BASE_URL="${REVEN_BASE_URL:-https://dev.wangyiyang.cc}"
readonly AUTH_USER="${REVEN_BASIC_AUTH_USER:?REVEN_BASIC_AUTH_USER is required}"
readonly AUTH_PASSWORD="${REVEN_BASIC_AUTH_PASSWORD:?REVEN_BASIC_AUTH_PASSWORD is required}"
readonly AUTHORITY="${BASE_URL#*://}"
readonly HOST_PORT="${AUTHORITY%%/*}"
readonly HOST="${HOST_PORT%%:*}"
unset REVEN_BASIC_AUTH_USER REVEN_BASIC_AUTH_PASSWORD

if [[ "${BASE_URL}" != https://* ]] && [[ "${REVEN_ALLOW_HTTP_LOCALHOST:-}" != "1" ]]; then
  echo "REVEN_BASE_URL must use HTTPS" >&2
  exit 2
fi
if [[ "${BASE_URL}" == http://* ]] && [[ ! "${BASE_URL}" =~ ^http://(localhost|127\.0\.0\.1)(:[0-9]+)?$ ]]; then
  echo "HTTP exception is restricted to localhost" >&2
  exit 2
fi
if [[ "${HOST_PORT}" == *"@"* ]] || [[ -z "${HOST}" ]]; then
  echo "REVEN_BASE_URL must not contain credentials" >&2
  exit 2
fi
if [[ "${AUTH_USER}${AUTH_PASSWORD}" =~ [[:space:]] ]]; then
  echo "Basic Auth credentials must not contain whitespace" >&2
  exit 2
fi

set +x
NETRC_FILE="$(mktemp "${TMPDIR:-/tmp}/reven-smoke.XXXXXX")"
readonly NETRC_FILE
cleanup() {
  unlink "${NETRC_FILE}"
}
trap cleanup EXIT
chmod 600 "${NETRC_FILE}"
printf 'machine %s\nlogin %s\npassword %s\n' \
  "${HOST}" "${AUTH_USER}" "${AUTH_PASSWORD}" >"${NETRC_FILE}"
curl --fail --silent --show-error \
  --request GET \
  --connect-timeout 5 \
  --max-time 15 \
  --netrc-file "${NETRC_FILE}" \
  "${BASE_URL%/}/api/health" |
  grep --fixed-strings '"status":"ok"'
