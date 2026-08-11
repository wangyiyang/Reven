#!/bin/sh
set -eu

image="${REVEN_IMAGE:-}"
pattern='^registry\.cn-hangzhou\.aliyuncs\.com/wangyiyang/reven@sha256:[0-9a-f]{64}$'

if ! printf '%s\n' "$image" | grep -Eq "$pattern"; then
  echo "REVEN_IMAGE must be registry.cn-hangzhou.aliyuncs.com/wangyiyang/reven@sha256:<64 lowercase hex>" >&2
  exit 1
fi
