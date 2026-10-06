# 技术设计：公开镜像 GHCR 发布路径

## 决策

- **镜像（mirror）而非双构建**：同一本地镜像 tag 后推送 GHCR。内容寻址 digest 与 registry 无关，两 registry 的 `repo@digest` 等价，发布说明中的 digest 两个入口通用。
- **推送顺序**：build → Trivy CRITICAL 门禁 → push ACR（生产链不动）→ login GHCR（`secrets.GITHUB_TOKEN`，job 加 `packages: write`）→ tag + push GHCR → SBOM → digest 解析。门禁先于一切推送，满足 R2。
- **镜像归属标签**：build 时加 `--label org.opencontainers.image.source=https://github.com/$GITHUB_REPOSITORY`，使 GHCR 包链接仓库（后续可见性随仓库，README 显示包入口）。
- **compose.image.yml 用 `!reset` 清除 build**：`build: !reset` + `image: ${REVEN_IMAGE:?...}`。文档已要求 Compose ≥2.24.4（`!override` 同机制）。用户文件列表追加该文件即切换到镜像入口，`dc build reven` 不再执行。
- **私有期行为**：仓库仍为私有时 GHCR 包不可匿名拉取，文档明确"镜像入口在仓库公开后可用"，不作为当前阻塞。

## 校验设计

- 本地/CI：`docker compose -f docker-compose.yml -f compose.image.yml config` 合并校验（CI 用全零 digest 环境变量注入）；actionlint 校验 release.yml/ci.yml。
- 交付验收：下次 tag 发布后核对 GHCR digest 与 ACR 一致（写入子任务 #4 发布清单）。

## 风险

- GHCR 包默认私有：转公开后需确认包可见性（或随仓库联动）——列入子任务 #4 人工清单。
- `latest` tag 在 GHCR 同样存在，文档始终引导 digest 固定，`latest` 仅便利浏览。
