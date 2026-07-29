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

mkdir "$project/vendor/.doocs-md.lock"
if (cd -P "$project" && ./scripts/vendor_doocs.sh >/dev/null 2>"$test_root/lock.err"); then
  echo "expected existing lock failure" >&2
  exit 1
fi
grep -Fq "vendor update lock exists; confirm no updater is running, then remove vendor/.doocs-md.lock" "$test_root/lock.err"
grep -qx "original" "$project/vendor/doocs-md/marker"
rmdir "$project/vendor/.doocs-md.lock"

ln -s "$test_root/lock-target" "$project/vendor/.doocs-md.lock"
if (cd -P "$project" && ./scripts/vendor_doocs.sh >/dev/null 2>"$test_root/lock.err"); then
  echo "expected symlink lock failure" >&2
  exit 1
fi
[[ -L "$project/vendor/.doocs-md.lock" ]]
grep -qx "original" "$project/vendor/doocs-md/marker"
unlink "$project/vendor/.doocs-md.lock"

(cd -P "$project" && REVEN_VENDOR_TESTING=1 REVEN_VENDOR_TEST_HOOK=hold_lock \
  ./scripts/vendor_doocs.sh >"$test_root/first.out" 2>"$test_root/first.err") &
first_pid=$!
for _attempt in $(seq 1 100); do
  [[ ! -d "$project/vendor/.doocs-md.lock" ]] || break
  sleep 0.05
done
[[ -d "$project/vendor/.doocs-md.lock" ]]
if (cd -P "$project" && ./scripts/vendor_doocs.sh >/dev/null 2>"$test_root/second.err"); then
  echo "expected concurrent updater failure" >&2
  exit 1
fi
grep -Fq "vendor update lock exists" "$test_root/second.err"
grep -qx "original" "$project/vendor/doocs-md/marker"
[[ ! -e "$project/vendor/.doocs-md.backup" ]]
[[ -z "$(find "$project/vendor" -maxdepth 1 -name '.doocs-md.staging.*' -print -quit)" ]]
touch "$project/vendor/.doocs-md.lock/release"
wait "$first_pid"
[[ ! -e "$project/vendor/.doocs-md.lock" ]]
[[ ! -e "$project/vendor/.doocs-md.backup" ]]
[[ -z "$(find "$project/vendor" -maxdepth 1 -name '.doocs-md.staging.*' -print -quit)" ]]
rm -rf -- "$project/vendor/doocs-md"
mkdir "$project/vendor/doocs-md"
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
