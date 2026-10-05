# 开源 Alpha 发布准备（授权、安全清理与通用自托管）

> 来源：GitHub Issue #127（OPC-112）。父任务，负责需求全集、任务图与跨子任务验收；实施在子任务中进行。

## Goal

完成 Reven 首个开源 Alpha 的发布准备，使外部开发者能够在不使用维护者账号、凭据或私有基础设施的情况下，按照文档独立部署并跑通一条核心流程。

首版定位：**面向独立创作者的单用户、自托管内容运营工作台**（RSS 内容发现 + 飞书通知为核心场景）。

## Background

Issue #127 基于 `7761675` 编写；本任务以 main（`b27ce2b`）为基线重新核查，当前差距：

| Issue 清单项 | 基线状态 | 当前状态（HEAD） |
|---|---|---|
| 1.1 LICENSE 与元数据 | 缺失 | ✅ 已补齐（Apache-2.0 + pyproject/package.json + THIRD_PARTY_NOTICES） |
| 1.2 第三方许可核对 | 未做 | 🔶 licenses/REVIEW.md 自列 8 个 JS 包缺原文、DeepSeek harness 322 项依赖未核验 |
| 1.3 Doocs Token 清理 | 待核实 | ❌ **严重**：15 个 `ghp_` token 仍在 git 历史（`e43726a` 引入 vendor/doocs-md，`7edafd7` 仅删文件未清历史） |
| 1.4 全历史密钥扫描 | 未做 | ❌ gitleaks 未安装，361 个 commit 未扫描 |
| 1.5 个人/业务信息清理 | 未做 | 🔶 workspace/ 未进历史 ✅；但 .gitignore 未排除 workspace/、`.trellis/workspace`；.trellis 跟踪 318 文件含本机路径与 journal；docs/runbook.md 含个人域名（已声明维护者专属） |
| 2.1 HTTPS/Origin/CSRF/Cookie | 拒绝 HTTPS | ✅ 协议层已支持（origin.py 双协议、CSRF fail-closed、Secure cookie 随协议）；HTTP 边界已写入文档 |
| 2.2 个人环境参数通用化 | 个人值遍布 | 🔶 自托管链路已通用；残留：config.py:18 默认值、根 .env.example、infra/caddy、infra/compose、smoke.sh 默认值 |
| 2.3 公开镜像路径 | 仅私有 ACR | ❌ 无 GHCR 流程；validate/deploy 脚本正则强绑私有 ACR |
| 2.4 自托管文档独立 | 未验证 | ✅ docs/self-hosting*.md 全程通用占位符，runbook 已隔离声明 |
| 3.1 README | 缺失 | ✅ 目标用户/场景/Alpha 边界/限制齐备 |
| 3.2 Quick Start | 缺失 | ✅ docs/self-hosting.md 完整（含环境/配置/密钥/启动/首登/核心流程） |
| 3.3 集成清单 | 缺失 | ✅ docs/integrations.md 齐备（7 类集成、降级行为、权限、费用） |
| 3.4 升级/备份/回滚 | 缺失 | ✅ self-hosting-operations.md 齐备（含迁移限制） |
| 3.5 CONTRIBUTING/SECURITY | 缺失 | 🔶 CONTRIBUTING ✅；SECURITY.md 形式存在但 Private vulnerability reporting 因仓库私有未启用 |
| 3.6 Alpha 发布说明 | 缺失 | ❌ 无 CHANGELOG / Release notes / GitHub Release |

## Task Map（子任务）

| 顺序 | 子任务 | 覆盖 | 可独立验收 |
|---|---|---|---|
| 1 | secret-history-audit | 1.3 + 1.4 + 验收#2 | gitleaks 全历史扫描通过、token 全部吊销、脱敏记录归档 |
| 2 | repo-personal-binding-cleanup | 1.5 + 2.2 残留 | .gitignore 完备、个人值清单清零（维护者生产链路除外） |
| 3 | public-image-ghcr | 2.3 | GHCR 镜像可拉取、校验脚本接受外部镜像、ACR 生产链不回退 |
| 4 | alpha-release-delivery | 3.5 + 3.6 | SECURITY 渠道启用、Alpha release notes 发布 |
| 5 | clean-env-acceptance | 验收#3 #4 | 干净环境独立安装 + HTTPS 验收记录（脱敏） |

依赖：1 必须先做（安全阻塞）；2、3 可并行；4 依赖仓库转公开（人工操作，排在 1、2 之后）；5 最后。

## Requirements（跨子任务）

R1. 全部真实凭据先撤销/轮换，再处理仓库与历史；扫描结果仅保存脱敏信息。
R2. 镜像来源通用化保留现有部署的安全约束，不接受任意未校验镜像作为替代。
R3. 维护者生产链路（infra/caddy、infra/compose、deploy_reven.sh、runbook.md）允许保留个人值，但必须与通用自托管路径在物理/文档上清晰分层。
R4. 如需重写 Git 历史，先评估现有克隆、分支、外部引用（Linear 链接、PR 记录）的影响。
R5. 单用户、自托管是首版边界；多租户 SaaS（#121）、完整 ERP、更多 Agent 能力不在本任务范围。

## Acceptance Criteria（跨子任务，对齐 Issue #127）

- [x] 项目级许可证明确，第三方许可核对闭环，必要声明随源码保留
- [x] 拟公开内容与完整历史完成扫描复核，无未处理的真实凭据；有脱敏检查记录
- [ ] 陌生开发者无需维护者账号、凭据或私有镜像权限，仅按文档即可安装并首次登录（子任务 #5）
- [ ] HTTPS 部署下认证、CSRF、会话 Cookie 行为正确，跑通文档指定核心流程（子任务 #5）
- [x] 质量检查通过（v0.5.0 release 流水线全绿：ruff/mypy/pytest 覆盖、vitest/tsc/build、镜像扫描门禁）
- [x] README、Quick Start、贡献指南、安全反馈方式、Alpha 已知限制齐备

## Out of Scope

- 多租户 SaaS（#121）、完整 ERP、更多 Agent 能力
- 功能开发（本任务只做发布准备，不改产品功能）
- 第三方许可原文补齐中涉及采购/法务的动作（仅做清单与缺口记录）
