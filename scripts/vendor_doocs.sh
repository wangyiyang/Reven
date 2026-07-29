#!/usr/bin/env bash
set -euo pipefail

readonly REPOSITORY="https://github.com/doocs/md.git"
readonly COMMIT="c37c1d6cc0e0a259de20305b9e4c3b59c7029da7"
readonly TARGET="vendor/doocs-md"

repository_root="$(git rev-parse --show-toplevel)"
if [[ "$PWD" != "$repository_root" ]]; then
  echo "run from the repository root" >&2
  exit 1
fi
if [[ "$TARGET" != "vendor/doocs-md" ]]; then
  echo "unsafe vendor target" >&2
  exit 1
fi

temporary_directory="$(mktemp -d)"
trap 'rm -rf -- "$temporary_directory"' EXIT

git init "$temporary_directory/upstream"
git -C "$temporary_directory/upstream" remote add origin "$REPOSITORY"
git -C "$temporary_directory/upstream" sparse-checkout init --no-cone
git -C "$temporary_directory/upstream" sparse-checkout set \
  packages/core packages/shared packages/config patches/juice@11.1.1.patch LICENSE
git -C "$temporary_directory/upstream" fetch --depth=1 origin "$COMMIT"
git -C "$temporary_directory/upstream" checkout --detach FETCH_HEAD

rm -rf -- "$repository_root/$TARGET"
mkdir -p "$repository_root/$TARGET/packages" "$repository_root/$TARGET/patches"
cp -R "$temporary_directory/upstream/packages/core" "$repository_root/$TARGET/packages/"
cp -R "$temporary_directory/upstream/packages/shared" "$repository_root/$TARGET/shared"
cp -R "$temporary_directory/upstream/packages/config" "$repository_root/$TARGET/config"
cp "$temporary_directory/upstream/patches/juice@11.1.1.patch" "$repository_root/$TARGET/patches/"
cp "$temporary_directory/upstream/LICENSE" "$repository_root/$TARGET/"

cat >"$repository_root/$TARGET/UPSTREAM.md" <<EOF
# Doocs Markdown 上游信息

- 仓库：$REPOSITORY
- 固定提交：\`$COMMIT\`
- 同步日期：$(date -u +%F)
- 许可证：WTFPL v2，原文见同目录 \`LICENSE\`

## 本地适配边界

仅同步渲染所需的 \`packages/core\`、\`shared\`、\`config\`、Juice 补丁和许可证。
不引入 Doocs Web/Vue 应用；Reven 的适配代码独立位于 \`renderer\`。
EOF
