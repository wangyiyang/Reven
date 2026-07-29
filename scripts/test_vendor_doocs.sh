#!/usr/bin/env bash
set -euo pipefail

readonly SOURCE_ROOT="$(git rev-parse --show-toplevel)"
test_root="$(mktemp -d)"
trap 'rm -rf -- "$test_root"' EXIT

upstream="$test_root/upstream"
project="$test_root/project"
mkdir -p "$upstream/packages" "$upstream/patches" "$project/vendor/doocs-md" "$project/scripts"
cp -R "$SOURCE_ROOT/vendor/doocs-md/packages/core" "$upstream/packages/"
cp -R "$SOURCE_ROOT/vendor/doocs-md/shared" "$upstream/packages/shared"
cp -R "$SOURCE_ROOT/vendor/doocs-md/config" "$upstream/packages/config"
cp "$SOURCE_ROOT/vendor/doocs-md/patches/juice@11.1.1.patch" "$upstream/patches/"
cp "$SOURCE_ROOT/vendor/doocs-md/LICENSE" "$upstream/"

git -C "$upstream" init -q
git -C "$upstream" config user.name "Vendor Test"
git -C "$upstream" config user.email "vendor-test@example.invalid"
git -C "$upstream" add .
GIT_AUTHOR_DATE="2026-05-31T02:14:43Z" GIT_COMMITTER_DATE="2026-05-31T02:14:43Z" \
  git -C "$upstream" commit -qm "fixture"
commit="$(git -C "$upstream" rev-parse HEAD)"

sed \
  -e "s|readonly REPOSITORY=.*|readonly REPOSITORY=\"file://$upstream\"|" \
  -e "s|readonly COMMIT=.*|readonly COMMIT=\"$commit\"|" \
  "$SOURCE_ROOT/scripts/vendor_doocs.sh" >"$project/scripts/vendor_doocs.sh"
chmod +x "$project/scripts/vendor_doocs.sh"
git -C "$project" init -q
echo "original" >"$project/vendor/doocs-md/marker"

for fault in after_copy after_backup after_install; do
  if (cd -P "$project" && REVEN_VENDOR_FAULT="$fault" ./scripts/vendor_doocs.sh >/dev/null 2>"$test_root/fault.err"); then
    echo "expected injected failure at $fault" >&2
    exit 1
  fi
  grep -Fq "injected vendor failure: $fault" "$test_root/fault.err"
  grep -qx "original" "$project/vendor/doocs-md/marker"
done

rm -rf -- "$project/vendor/doocs-md"
if (cd -P "$project" && REVEN_VENDOR_FAULT="after_install" ./scripts/vendor_doocs.sh >/dev/null 2>"$test_root/fault.err"); then
  echo "expected injected failure without an existing target" >&2
  exit 1
fi
grep -Fq "injected vendor failure: after_install" "$test_root/fault.err"
[[ ! -e "$project/vendor/doocs-md" ]]

(cd -P "$project" && ./scripts/vendor_doocs.sh >/dev/null)
first_hash="$(find "$project/vendor/doocs-md" -type f -print | LC_ALL=C sort | xargs shasum | shasum)"
(cd -P "$project" && ./scripts/vendor_doocs.sh >/dev/null)
second_hash="$(find "$project/vendor/doocs-md" -type f -print | LC_ALL=C sort | xargs shasum | shasum)"
[[ "$first_hash" == "$second_hash" ]]
[[ ! -e "$project/vendor/.doocs-md.backup" ]]
