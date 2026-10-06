# 公开镜像 GHCR 发布路径

> 父任务：09-29-open-source-alpha-release（Issue #127 子任务 #3）。

## Goal

让外部用户可以不依赖维护者私有 ACR、也不必本地构建，直接拉取公开镜像部署；同时完整保留维护者生产链路与镜像完整性校验。

## Background

- release.yml 只构建推送私有 ACR（`registry.cn-hangzhou.aliyuncs.com/wangyiyang/reven`）后 SSH 部署；无 GHCR/docker.io 流程。
- `validate_reven_image.sh` / `deploy_reven.sh` 正则强绑私有 ACR——二者属维护者生产链路（允许清单），**外部路径不经过它们**，无需改动。
- 自托管默认链路是源码构建（`infra/self-host/docker-compose.yml` build 段），本身不依赖任何 registry；缺口是"没有公开镜像入口"。
- CI 的"Verify embedded release infra"会将 `infra/` 全量嵌入镜像并 diff，新增 compose 文件必须随仓库提交。

## Requirements

1. **GHCR 推送**：release.yml `image` 任务在 Trivy 门禁通过后、把同一镜像镜像推送到 `ghcr.io/<owner>/reven`（`<owner>` 取自 `GITHUB_REPOSITORY_OWNER`），推送 version 与 latest 两个 tag；ACR 推送与 SSH 部署流程不变。
2. **供应链约束保留**：Trivy CRITICAL 门禁与 SBOM 在推送前完成，对两个 registry 一视同仁；镜像带 `org.opencontainers.image.source` 标签链接回仓库。
3. **镜像入口覆盖文件**：新增 `infra/self-host/compose.image.yml`，以 `!reset` 移除源码 build，使用 `REVEN_IMAGE`（digest 固定）拉取；`.env.example` 增加注释示例。
4. **文档**：`docs/self-hosting.md` 增加"使用公开镜像"入口（含 digest 固定与拉取校验说明）；`docs/self-hosting-operations.md` 升级节补充镜像用户的升级步骤；README 入口描述更新。
5. **CI 校验**：container full 任务增加 self-host compose 镜像覆盖合并配置的 `config` 校验。

## Acceptance Criteria

- [ ] tag 推送时 GHCR 出现与 ACR 同一 digest 的 version/latest 镜像
- [ ] 外部用户按文档可用 `compose.image.yml` + digest 启动，无需维护者账号
- [ ] 维护者 ACR 部署链路与 validate 脚本零改动
- [ ] actionlint / compose config 校验通过，CI container full 全绿

## Out of Scope

- GHCR 包可见性设置（仓库转公开时联动，子任务 #4 的发布清单项）
- Release notes/CHANGELOG 中自动附 digest（子任务 #4）
- ARM64 镜像（README 已声明未验证）
