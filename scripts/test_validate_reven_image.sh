#!/usr/bin/env bash
set -euo pipefail

readonly VALIDATOR="$(git rev-parse --show-toplevel)/scripts/validate_reven_image.sh"
readonly DIGEST="$(printf 'a%.0s' {1..64})"

assert_valid() {
  REVEN_IMAGE="$1" "$VALIDATOR"
}

assert_invalid() {
  if REVEN_IMAGE="$1" "$VALIDATOR" >/dev/null 2>&1; then
    echo "expected invalid image reference: $1" >&2
    exit 1
  fi
}

assert_valid "registry.cn-hangzhou.aliyuncs.com/wangyiyang/reven@sha256:${DIGEST}"
assert_invalid "registry.cn-hangzhou.aliyuncs.com/wangyiyang/reven:v0.1.1"
assert_invalid "registry.cn-hangzhou.aliyuncs.com/wangyiyang/other@sha256:${DIGEST}"
assert_invalid "ghcr.io/wangyiyang/reven@sha256:${DIGEST}"
