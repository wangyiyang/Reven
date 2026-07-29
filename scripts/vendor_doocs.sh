#!/usr/bin/env bash
set -euo pipefail

readonly REPOSITORY="https://github.com/doocs/md.git"
readonly COMMIT="c37c1d6cc0e0a259de20305b9e4c3b59c7029da7"
readonly TARGET="vendor/doocs-md"
readonly BACKUP="vendor/.doocs-md.backup"

repository_root="$(git rev-parse --show-toplevel)"
vendor_root="$repository_root/vendor"
target_path="$repository_root/$TARGET"
backup_path="$repository_root/$BACKUP"
staging_path=""
temporary_directory=""
backup_active=false
completed=false

fail() {
  echo "$1" >&2
  exit 1
}

validate_environment() {
  [[ "$PWD" == "$repository_root" ]] || fail "run from the repository root"
  [[ "$TARGET" == "vendor/doocs-md" && "$BACKUP" == "vendor/.doocs-md.backup" ]] || fail "unsafe vendor paths"
  [[ -d "$vendor_root" && ! -L "$vendor_root" ]] || fail "vendor root must be a real directory"
  case "${REVEN_VENDOR_FAULT:-}" in
    ""|after_copy|after_backup|after_install) ;;
    *) fail "invalid vendor fault point" ;;
  esac
}

restore_interrupted_backup() {
  [[ -e "$backup_path" ]] || return 0
  [[ -d "$backup_path" && ! -L "$backup_path" ]] || fail "unsafe interrupted vendor backup"
  if [[ -e "$target_path" ]]; then
    fail "vendor backup and target both exist; manual recovery required"
  fi
  mv "$backup_path" "$target_path"
  echo "restored interrupted vendor backup" >&2
}

safe_remove_temporary() {
  local path="$1"
  [[ -n "$path" && "$path" == "$vendor_root"/.doocs-md.* ]] || fail "unsafe temporary path"
  [[ ! -L "$path" ]] || fail "refusing to remove temporary symlink"
  [[ ! -e "$path" ]] || rm -rf -- "$path"
}

cleanup() {
  local status=$?
  if [[ "$completed" != true && "$backup_active" == true && -d "$backup_path" ]]; then
    if [[ -e "$target_path" ]]; then
      failed_path="$(mktemp -d "$vendor_root/.doocs-md.failed.XXXXXX")"
      rmdir "$failed_path"
      mv "$target_path" "$failed_path"
      safe_remove_temporary "$failed_path"
    fi
    mv "$backup_path" "$target_path"
  fi
  [[ -z "$staging_path" ]] || safe_remove_temporary "$staging_path"
  [[ -z "$temporary_directory" ]] || safe_remove_temporary "$temporary_directory"
  exit "$status"
}

trigger_fault() {
  [[ "${REVEN_VENDOR_FAULT:-}" != "$1" ]] || fail "injected vendor failure: $1"
}

write_upstream_metadata() {
  local destination="$1"
  local commit_date="$2"
  cat >"$destination/UPSTREAM.md" <<EOF
# Doocs Markdown 上游信息

- 仓库：$REPOSITORY
- 固定提交：\`$COMMIT\`
- 固定提交日期：$commit_date
- 许可证：WTFPL v2，原文见同目录 \`LICENSE\`

## 本地适配边界

仅同步渲染所需的 \`packages/core\`、\`shared\`、\`config\`、Juice 补丁和许可证。
不引入 Doocs Web/Vue 应用；Reven 的适配代码独立位于 \`renderer\`。
EOF
}

validate_staging() {
  local destination="$1"
  [[ -f "$destination/packages/core/package.json" ]] || fail "missing vendored core"
  [[ -f "$destination/shared/package.json" ]] || fail "missing vendored shared"
  [[ -f "$destination/config/package.json" ]] || fail "missing vendored config"
  [[ -f "$destination/patches/juice@11.1.1.patch" ]] || fail "missing Juice patch"
  [[ -f "$destination/LICENSE" && -f "$destination/UPSTREAM.md" ]] || fail "missing vendor metadata"
  grep -Fq "$COMMIT" "$destination/UPSTREAM.md" || fail "incorrect vendor commit"
  [[ ! -e "$destination/web" && ! -e "$destination/packages/web" ]] || fail "unexpected Doocs web application"
}

validate_environment
restore_interrupted_backup
trap cleanup EXIT
trap 'exit 130' INT TERM

temporary_directory="$(mktemp -d "$vendor_root/.doocs-md.upstream.XXXXXX")"
staging_path="$(mktemp -d "$vendor_root/.doocs-md.staging.XXXXXX")"
git init "$temporary_directory/upstream"
git -C "$temporary_directory/upstream" remote add origin "$REPOSITORY"
git -C "$temporary_directory/upstream" sparse-checkout init --no-cone
git -C "$temporary_directory/upstream" sparse-checkout set \
  packages/core packages/shared packages/config patches/juice@11.1.1.patch LICENSE
git -C "$temporary_directory/upstream" fetch --depth=1 origin "$COMMIT"
git -C "$temporary_directory/upstream" checkout --detach FETCH_HEAD
commit_date="$(git -C "$temporary_directory/upstream" show -s --format=%cs "$COMMIT")"

mkdir -p "$staging_path/packages" "$staging_path/patches"
cp -R "$temporary_directory/upstream/packages/core" "$staging_path/packages/"
cp -R "$temporary_directory/upstream/packages/shared" "$staging_path/shared"
cp -R "$temporary_directory/upstream/packages/config" "$staging_path/config"
cp "$temporary_directory/upstream/patches/juice@11.1.1.patch" "$staging_path/patches/"
cp "$temporary_directory/upstream/LICENSE" "$staging_path/"
write_upstream_metadata "$staging_path" "$commit_date"
validate_staging "$staging_path"
trigger_fault after_copy

if [[ -e "$target_path" ]]; then
  [[ -d "$target_path" && ! -L "$target_path" ]] || fail "vendor target must be a real directory"
  mv "$target_path" "$backup_path"
  backup_active=true
fi
trigger_fault after_backup
mv "$staging_path" "$target_path"
staging_path=""
trigger_fault after_install

completed=true
if [[ "$backup_active" == true ]]; then
  safe_remove_temporary "$backup_path"
  backup_active=false
fi
safe_remove_temporary "$temporary_directory"
temporary_directory=""
