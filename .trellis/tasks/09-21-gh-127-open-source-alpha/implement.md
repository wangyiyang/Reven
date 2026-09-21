# #127 实施与验证清单

> 合并范围更新：`main` 的 `7edafd7`（#128）已移除 Notion、稿件发布、renderer、Doocs 与 Ruby/bubblewrap 运行依赖。用户要求本分支解决与 main 的冲突，因此当前实施保留该产品决策，首次流程改为 RSS → 人工审核 → Reven 本地素材库；以下早期设计与验收记录中涉及退役能力的内容仅保留为历史依据。当前合并验证见 `research/merge-main-validation.md`。

## 前置状态

- [x] 创建 `codex/gh-127-open-source-alpha` worktree，基于 `origin/main` 的 `7761675`。
- [x] 确认商业使用、首次核心流程、生产兼容性、Apache-2.0、个人原创版权署名及 Linux AMD64 范围。
- [x] 完成研究文件、PRD 收敛与上下文清单验证（implement/check 各 8 条，校验通过）。
- [x] 最终规划已批准（用户：“开始实施”），已运行 `task.py start`。

## 执行顺序

### 1. 开源材料与历史检查（R1、R2）

- [x] 安装/使用固定版本扫描工具，记录版本和扫描引用范围；扫描当前树及拟公开全部可达历史，输出脱敏报告到仓库外。
- [ ] 将需要处理的命中整理为文件/行号/提交/分类/处理结论，处理真实凭据与历史风险后才能宣称清理完成。
- [ ] 核对 Trellis 固定版本许可及模板条款、Doocs、锁定依赖、字体和运行时分发物。
- [x] 添加原创 Apache-2.0 LICENSE、包元数据和第三方许可清单；补齐应保留的原始声明。
- [x] 最小移除 Doocs 无用凭据配置和孤立导出；修改 `scripts/vendor_doocs.sh` 与 `scripts/test_vendor_doocs.sh` 防止回灌。
- [ ] 复核文档、任务日志和仓库附属内容中的隐私信息；处理完再次扫描。

验证：vendoring fixture、renderer 回归、专用扫描及许可清单复核。任何未确认许可或真实秘密命中均需显式记录，不以广泛忽略规则压掉。

### 2. HTTPS 与现有 HTTP 兼容（R3、R5）

- [x] 补充先失败的配置/认证行为用例：合法 HTTPS、规范化边界、非法 origin、HTTPS Secure Cookie、既有 HTTP 行为和 CSRF。
- [x] 最小修改 Settings origin 校验及必要认证逻辑；保持 alias、会话和 MCP 契约。
- [x] 验证现有 HTTP Caddy、端口及部署回滚测试继续通过；不注入影响全域名的 HSTS。

验证：`test_config.py`、`security/test_auth.py`、`security/test_csrf.py`、`e2e/test_http_deployment.py`；实际 HTTPS 入口另在第 5 步验证。

### 3. 通用自托管入口（R4、R5）

- [x] 添加 `infra/self-host/` Compose、Caddy 配置和通用示例；复用现有 Dockerfile，从源码构建。
- [x] 装配 PostgreSQL 17、健康依赖、迁移、持久卷及非 root 权限；数据库与应用原始端口不直接对公网开放。
- [x] 保留只读根文件系统、资源限制、cap_drop、沙箱与 no-new-privileges。
- [x] 明确 HTTPS 公网路径与 loopback HTTP 体验路径，校验配置的一致性。
- [x] 更新 Dockerfile 专属 ignore 规则，排除嵌套 `.env`、秘密及运行态文件；保留必要示例和许可证。
- [x] 保持现有 ACR digest 校验及生产流程；不增加未经验证的任意远程镜像入口。

验证：Compose 渲染与 Caddy 配置校验、构建上下文排除、空卷启动、数据库健康依赖、运行 UID、数据持久化及原生产脚本回归。

### 4. 对外文档与协作（R6、R7）

- [x] 重写 README 安装入口与 Alpha 功能边界，整理 Quick Start。
- [x] 按真实 UI/API 写 RSS + Notion 指南，说明两类数据源、关键词、权限、调度等待、降级状态和幂等核对。
- [x] 将博客/微信/COS/AI/通知作为后续集成说明，列清必需条件和第三方费用。
- [x] 完成贡献、安全反馈、升级、数据库与主密钥备份、恢复及回滚文档。
- [x] 记录 Linux AMD64 支持证据，ARM64/Docker Desktop 列为未正式验证。
- [ ] 核对私密漏洞反馈入口在公开发布时确实可用；无法验证时不得虚构已启用状态。

### 5. 综合验收与收尾（AC1–AC7）

- [x] 在 worktree 安装锁定依赖，启动独立测试数据库，确认测试不会连接生产库。
- [x] 运行受影响层的检查，修复有实质影响的问题；完成 Trellis 全范围检查与必要 spec 同步。
- [x] 在 Linux AMD64 的隔离环境用空卷按 Quick Start 完成实际构建/运行/HTTPS/沙箱验证；如用 CI，采用独立验证入口，不触发生产部署。
- [ ] 对用户指定的 Notion 测试空间完成真实 RSS 流程验收，记录脱敏证据；未具备目标时先完成其余工作，再请求具体目标，相关 AC 保持未完成。
- [x] 验证容器重建后的数据/会话持久性、备份恢复后的加密集成与主密钥行为；旧部署升级/失败回滚回归通过。不兼容 schema 降级及真实生产迁移不在本次实测范围。
- [x] 最终工作树再次专用扫描，仅保留 2 条确认的假值/示例；核验报告已形成，未闭合门槛逐项保留。
- [x] 已按关注点提交并创建草稿 PR #129；使用关联关系，未声明 Closes #127，剩余发布门槛已写入。

## 验证命令基线

以下为实施阶段执行命令，运行前按隔离环境设置专用测试数据库，不复用生产 `.env`。

```bash
uv sync --frozen --all-packages
pnpm install --frozen-lockfile
uv run ruff check server
uv run ruff format --check server
uv run mypy server/src
uv run alembic -c server/migrations/alembic.ini upgrade head
uv run pytest server/tests --cov=reven --cov-report=term-missing --cov-fail-under=80
pnpm --filter @reven/renderer test
pnpm --filter @reven/web test --run
pnpm build
sh scripts/test_vendor_doocs.sh
sh scripts/test_deploy_reven.sh
git diff --check
```

- `TEST_DATABASE_URL` 必须设置到本次隔离数据库，禁止以跳过数据库测试作为成功证据。
- 修改 workflow 时运行 actionlint；普通 PR/main 容器构建仍保持跳过。
- 如修改 shell 逻辑，运行对应行为测试及 shellcheck；工具不可用时先补工具或明确未完成。
- Compose/Caddy/扫描命令按最终文件路径与固定工具版本写入验收记录，不使用未审查的外部脚本。

## 代理工作边界

- 授权/资料代理：LICENSE、第三方声明、vendoring、扫描报告；不改认证和部署。
- 部署代理：后端 origin/认证及其测试、`infra/self-host/` 与必要 ignore；不改原生产发布语义。
- 主会话：需求和跨层协调、对外文档、验证集成与最终报告。
- 若文件所有权存在交叉，先调整分工；所有代理均不得撤销其他工作。

## 回滚与发布边界

- 不改变现有生产环境、仓库可见性或公开镜像状态。
- 不自动重写主分支历史；发现必须重写时，先提交具体影响和恢复方案。
- 不删除共享卷、生产数据或其他 worktree。
- 根许可证不覆盖第三方目录，发现许可问题时先保留/补齐原许可并重新核对分发物。
