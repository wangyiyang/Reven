#!/bin/sh
set -eu

image="${REVEN_IMAGE:-}"
component='[a-z0-9]+(([.]|_{1,2}|-+)[a-z0-9]+)*'
pattern="^ghcr\\.io/${component}/${component}@sha256:[0-9a-f]{64}$"

if ! printf '%s\n' "$image" | grep -Eq "$pattern"; then
  echo "REVEN_IMAGE must be ghcr.io/<owner>/<repository>@sha256:<64 lowercase hex>" >&2
  exit 1
fi
