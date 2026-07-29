#!/bin/sh
set -eu

image="${REVEN_IMAGE:-}"
pattern='^ghcr\.io/[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?/[A-Za-z0-9._-]+@sha256:[0-9a-f]{64}$'

if ! printf '%s\n' "$image" | grep -Eq "$pattern"; then
  echo "REVEN_IMAGE must be ghcr.io/<owner>/<repository>@sha256:<64 lowercase hex>" >&2
  exit 1
fi

path="${image#ghcr.io/}"
repository_with_digest="${path#*/}"
repository="${repository_with_digest%%@sha256:*}"
case "$repository" in
  . | ..)
    echo "REVEN_IMAGE must be ghcr.io/<owner>/<repository>@sha256:<64 lowercase hex>" >&2
    exit 1
    ;;
esac
