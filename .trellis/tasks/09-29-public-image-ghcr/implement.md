# 执行计划：公开镜像 GHCR 发布路径

分支：`chore/public-image-ghcr`（已建）。

1. **release.yml**：
   - `image` job 增加 `permissions: {contents: read, packages: write}`
   - build 步骤加 `--label org.opencontainers.image.source=...`
   - 新增 "Mirror production image to GitHub Container Registry" 步骤（ACR push 之后）
   - 验证：`actionlint .github/workflows/release.yml`
2. **infra/self-host/compose.image.yml**（新增）+ `.env.example` 注释示例。
   - 验证：`docker compose -f infra/self-host/docker-compose.yml -f infra/self-host/compose.image.yml config --quiet`（注入全零 digest 与必填变量）
3. **文档**：self-hosting.md 入口三选一改造、operations.md 升级补充、README 一行更新。
   - 验证：`grep` 核对镜像入口描述前后一致
4. **ci.yml**："Validate Compose and Caddy" 步骤追加 self-host 镜像覆盖合并校验。
   - 验证：`actionlint .github/workflows/ci.yml`
5. **质量门**：trellis-check 子代理检查 diff。
6. **提交并开 PR**（`feat(infra): 增加 GHCR 公开镜像发布与自托管镜像入口`），关联 Issue #127。

## 回滚点

全部为新增文件/步骤级改动；回滚 = revert 单 commit，不影响 ACR 生产链（无修改）。
