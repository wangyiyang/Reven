# CI 与发版镜像构建契约

## 1. 范围与触发

维护 `.github/workflows/ci.yml`、`release.yml` 或部署结构测试时遵守本契约。
Issue #115 修复了仅限制生产发布入口、却遗漏普通 CI 测试镜像构建的问题。

## 2. 调用签名

- CI：`pull_request` 指向 main、`push` 到 main、`workflow_call`，以及独立的 `workflow_dispatch`。
- `workflow_call.inputs.full` 与 `workflow_dispatch.inputs.full`：可选 boolean，默认 `false`。
- 手动 CI 在选择的分支执行；`full=true` 运行完整质量检查，不发布镜像、不触发生产部署。
- 发版：`push.tags: ['v*']`；quality-gate 调用 CI 并传入 `full: true`。
- 手动：`workflow_dispatch(operation: deploy | rollback, version?: string)` 使用已有镜像。

## 3. 行为契约

- `jobs.container.if` 必须为 `inputs.full`，不得再由变更路径启用。
- 普通 PR/main CI 不构建 `reven:test`；backend、migration、frontend 保留各自的路径过滤及 full 覆盖。
- changes 不输出 container，也不维护 container 路径过滤。
- backend 路径过滤包含 `infra/self-host/**`、`infra/caddy/**`、`infra/compose/**`、`infra/docker/Dockerfile.dockerignore`、`scripts/self_host*.py`，使自托管或生产入口配置单独变化时也运行对应回归；不因此开启 container。
- 发版完整 CI 保留容器运行、嵌入式 Agent、SBOM 和漏洞检查。正式 image 任务依赖 quality-gate 成功。
- 正式镜像构建和自动部署由 tag push 触发，不监听 `release.published`。
- 手动部署和回滚不构建镜像；不得为验证本契约实际触发生产部署。

## 4. 验证与失败矩阵

| 场景 | 容器任务 | 后续行为 |
| --- | --- | --- |
| PR/main push，任意改动路径 | skipped | 其他检查按路径执行 |
| workflow_call，未传 full 或 full=false | skipped | 其他检查按路径执行 |
| 手动 CI workflow_dispatch，full=true | 执行 | 完整验证当前分支；不运行 release/deploy |
| 手动 CI workflow_dispatch，full=false | skipped | 其他检查仍遵循路径条件 |
| 发版 workflow_call，full=true | 执行 | 完整质量检查通过后允许 image |
| quality-gate 失败 | 发版失败 | 不运行 image，不自动部署 |
| 手动部署或回滚 | 不运行 quality-gate/image | 解析已有镜像或上一健康镜像 |

GitHub 对 job-level `if` 跳过的检查按成功处理，即使它仍列为 required check，也不会阻止合并。
来源：[GitHub 条件执行文档](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-jobs-with-conditions)。

## 5. 正常、默认与错误示例

- 正常：推送版本 tag，完整 CI 验证测试镜像后，生产任务构建并推送正式镜像。
- 默认：仅修改 `web/**` 的 PR 运行 frontend 检查，container 跳过。
- 错误：给 container 条件追加任意路径匹配分支，导致日常代码改动再次构建镜像。

普通 PR 不构建容器，相关变更应在合并前手动运行 full 检查；发版仍强制运行完整质量门禁。

## 6. 必须覆盖的测试

`server/tests/security/test_deployment_automation.py` 应验证：

- CI 的 workflow_call/workflow_dispatch full 均为 boolean 且默认 false，container 只由 full 启用。
- container 路径过滤及输出已移除，其他任务仍具备各自的路径条件。
- 发版调用传入 full true、image 依赖 quality-gate，并保留 tag 与手动通道条件。
- 原有容器基础设施同步验证、部署脚本 smoke 检查仍存在。

修改条件时先确认新增回归断言在旧配置失败，再验证修复通过；工作流同时通过 actionlint。
不要只检查 release 触发器就推断仓库内其他工作流不构建镜像。

## 7. 错误与正确写法

```yaml
# 错误：任何匹配路径都会在普通 CI 构建镜像
if: inputs.full || needs.changes.outputs.container == 'true'

# 正确：由发版调用或手动输入显式启用完整验证
if: inputs.full
```


## 8. 自托管完整检查（#127，随 #128 精简运行时）

- 完整 container job 使用 `ubuntu-22.04` 原生 AMD64 runner；构建 `reven:test` 并拉取固定 PostgreSQL/Caddy 依赖后，执行 `python3 scripts/self_host_smoke.py`。
- 不安装自定义 AppArmor profile、不修改宿主 sysctl、不引用已退役的 renderer、Ruby、bubblewrap、seccomp-bwrap 或博客 fixture；保留 Docker 默认安全策略。
- 入口只接受原生 Linux AMD64 Docker 宿主与 AMD64 应用镜像；不将本机 ARM 仿真结果算作正式支持证据。
- 使用随机 `reven-ci-self-host-*` Compose project、空 named volumes、临时随机凭据；测试只复用本地 `reven:test`，`up --no-build --pull never`，不运行生产脚本。
- 临时 override 仅添加测试镜像身份；容器仍采用 self-host Compose 的非 root、readonly、cap_drop、no-new-privileges 和资源限制，不使用 privileged、额外 capabilities 或 unconfined。
- 验证顺序：HTTP 首页/健康/认证/CSRF/MCP拒绝 → 非 root 与许可文件 → 本地 RSS 采纳 → 重建全部容器后会话、素材、数据库与三个应用卷持久化 → 自托管可信 HTTPS → 真实生产 Caddy/Compose 的隔离网关。
- RSS fixture 使用禁用的测试源，直接写入独立数据库的确定性 candidate；通过真实 API 采纳为 saved、重复采纳并核对 saved_at 不变，重建容器后再次验证。不访问外部集成，不冒充真实 RSS 抓取或模型验收。
- HTTPS 只在临时测试 Caddyfile 添加 `tls internal`，导出根证书并明确传入客户端的 SSL trust store；不得使用 `curl -k`、CERT_NONE 或关闭 hostname 校验。正式 self-host 配置仍使用自动 ACME。
- 无论启动、断言或诊断在哪一阶段失败，先打印当前 project 状态，再清理该 project 的容器与卷。任何清理失败也必须显式失败；不能清理共享或生产卷。

相关回归：`server/tests/security/test_deployment_automation.py` 与 `test_self_host_smoke.py`，覆盖完整入口、默认安全策略、退役依赖不回灌、失败清理、项目隔离、集成环境隔离及原生架构门禁。

## 9. 生产统一 VPS 入口的完整验证

### 1. 范围与触发

修改生产 Caddy/Compose、SPA/asset 路由或烟测时遵守。Caddy validate 仅证明语法，不能
证明实际入口与共享静态卷可用。生产配置路径变化也必须选择 backend 回归。

### 2. 命令与配置签名

`python3 scripts/self_host_smoke.py` 是原生 Linux AMD64 full CI 入口，不触发生产部署。
生产网关阶段复用随机测试项目与隔离 PostgreSQL，加载真实生产 Compose/Caddy，再以
最终测试 override 固定本地 `reven:test`、清空生产 env_file、使用 loopback 端口和测试 CA。
Compose 插值的 REVEN_IMAGE 使用格式合法的假 ACR digest，实际镜像由 fixture 替换；
不能放宽生产受限部署脚本的 digest 校验。

### 3. 行为契约

- 原生产 site_common 路由原样运行，不复制另一个 SPA 模板。
- HTML/深链接使用 no-cache；实际 assets MIME 正确、immutable 一年缓存；缺失 assets 404。
- API JSON/匿名 401、内部 MCP 404、可信 TLS Cookie/CSRF 与静态安全头真实请求验证。
- HTTP index 与镜像 web index/release 一致；实际共享卷 Source/Name 相同，应用 RW=true、Caddy RW=false。
- 隔离 override 不读取项目真实 .env、不发布 80/443/3001，不修改宿主安全策略；失败同样清理随机项目与卷。

### 4. 验证与失败矩阵

| 场景 | 必须观察到的结果 |
| --- | --- |
| 深链接刷新 | 当前 index 200 HTML/no-cache |
| 真实 JS/CSS 或缺失 assets | 正确 MIME/immutable，或 404；不能返回 SPA HTML |
| API/内部 MCP | JSON/401 与 MCP 404；不能被 SPA 吞掉 |
| Caddy 静态卷可写或不同源 | 验收失败 |
| 任一网关阶段失败 | 原异常保留，随机项目及卷清理；清理失败也显式失败 |
| ARM/QEMU 或测试数据库 fixture skip | 不计正式完整验收通过 |

### 5. 正常、默认与错误示例

正常：先 backend 聚焦回归，再在实际发布分支执行 full CI，最终线上可信 HTTPS 验收。
默认：日常 PR 的 container 仍 skipped。错误：仅 Caddy validate/health=200 就宣布前端上线。

### 6. 必须覆盖的测试

生产配置结构、路径过滤、烟测覆盖/清理回归分别落在 test_http_deployment.py、
test_deployment_automation.py、test_self_host_smoke.py；真实路由请求由 full smoke 执行。
主线检查不能替代基于旧发布版本的补丁检查；补丁相对基线的业务/迁移/lock 差异必须为空。

### 7. 错误与正确写法

```yaml
# 错误：独立生产配置变更不会选择语言层回归。
backend:
  - 'server/**'

# 正确：保留已有路径，并补生产入口配置。
backend:
  - 'server/**'
  - 'infra/caddy/**'
  - 'infra/compose/**'
```
