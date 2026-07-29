#!/bin/sh
set -eu

image="${REVEN_IMAGE:-}"
case "$image" in
  ghcr.io/*@sha256:*) digest="${image##*@sha256:}" ;;
  *)
    echo "REVEN_IMAGE must be ghcr.io/<owner>/<repository>@sha256:<64 lowercase hex>" >&2
    exit 1
    ;;
esac

if [ "${#digest}" -ne 64 ]; then
  echo "REVEN_IMAGE sha256 digest must contain exactly 64 hex characters" >&2
  exit 1
fi
case "$digest" in
  *[!0-9a-f]*)
    echo "REVEN_IMAGE sha256 digest must use lowercase hex characters only" >&2
    exit 1
    ;;
esac
