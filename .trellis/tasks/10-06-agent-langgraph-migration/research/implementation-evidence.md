# Agent 迁移实施证据

## 阶段 1：原生框架与协议门槛（2026-10-06）

- Python 3.12.12；uv 解算并冻结安装成功。新增直接版本：LangChain 1.4.3、core 1.6.6、DeepSeek 1.1.1、OpenAI adapter 1.6.7、LangGraph 1.2.13、Postgres saver 3.1.2、psycopg 3.3.6、pool 3.3.3。checkpoint 4.2.0/OpenAI SDK 3.24.0 为锁定传递依赖。
- 默认阿里云索引尚未同步 LangGraph 1.2.13；8 个新增直接依赖显式绑定官方 PyPI。与 HEAD 比对，既有所有包版本及 registry 来源不变；最初全索引漂移已收敛，阶段 1 lock diff 为 +958/-0。
- 实际安装 DeepSeek 1.1.1 的响应保留 reasoning_content，后续请求遗漏它。`RevenChatDeepSeek` 在既有转换结果上补回字段；HTTP MockTransport 验证多轮 Chat Completions、工具 ID、消息顺序和兼容端点 /v1 规则。
- 模型 HTTP client 显式 trust_env=False，与现有 ProviderClients 一致，避免环境 SOCKS 代理污染；客户端可由应用生命周期注入和释放。
- 检查点使用固定 reven_agent_checkpoints schema、独立 psycopg 池，部署显式 setup，应用 open 不建表；运行调用 durability=sync。DSN 测试覆盖特殊字符、IPv6、SSL 映射及不支持参数拒绝，错误不回显 URL。
- JsonPlusSerializer 显式 allowed_msgpack_modules=None、pickle_fallback=False，无环境变量也严格限制模块构造；不允许还原 AgentContext 对象，安全内建 UUID/消息类型正常读回。图状态不保存可信 context 或密钥。

验证命令：最终 `uv sync --frozen --all-packages --python 3.12` 成功；新增 4 个源码模块 mypy 通过，8 个源码/测试文件 ruff check 与 format --check 通过。

`TEST_DATABASE_URL` 只指向为本任务新建的 PostgreSQL 17（localhost:55433/reven_agent_test）；未访问既有 55432 数据库。下列测试合计 **23 passed**：test_native_providers、test_native_checkpoint、test_native_graph。

1. 原生 create_agent 实际模型 HTTP 替身→跟进工具→ToolMessage→最终回答，ToolRuntime 注入真实宿主身份和调用 ID，模型 schema 不含 runtime/owner/run。
2. 关闭并重建检查点池和图后，从 PostgreSQL 读回多轮历史、reasoning_content 与 run metadata，下一轮请求正确回传原消息。
3. 两个删除动作先中断，未决策零工具效果；关闭重建后同 interrupt ID 恢复，有序 reject/approve 只执行第二个工具；禁止 edit/respond。
4. 工具执行前异常后，重建图以 ainvoke(None) 继续，原用户消息只出现一次，原 tool_call_id 保持。

证据边界：上述是同进程新 pool/新 graph 的真实数据库恢复，尚不等同于完整应用或 OS 进程重启。工具效果为隔离测试替身，业务账本/事务提交后崩溃、身份审批和完整 37 工具兼容需要后续阶段验证。安全配置中没有可用真实模型凭据，本轮真实上游模型 smoke **未验证**；不将 HTTP 替身结果冒充真实模型证据。

## 部署脚本与前端回归（2026-10-06）

- `scripts/native_agent_smoke.py` 在隔离 PostgreSQL 上实际执行两轮原生工具与 sync checkpoint，关闭/重建 pool 与 graph 后历史为 8 条；完成后 `ainvoke(None)` 没有第二次工具效果。另一个 Python 进程以原 thread UUID 读回 8 条历史成功。这是独立进程验证，完整容器重建尚待后续验收。
- self-host runner 在保留只读根目录、UID 10001、cap_drop、资源限制与可信测试 CA 的前提下，增加原生图工具循环和容器重建后的历史读取，活动卷不再含 dsh-data；旧卷不删除。部署和 runner 的聚焦回归 **35 passed**，属于配置/失败路径检查，不能代替实际容器运行。
- 前端无本次源码变更，`pnpm --dir web lint`、`pnpm --dir web exec vitest run`（**30 files / 247 passed**）、`pnpm --dir web build` 均通过。测试中既有 MSW body 已读与 Node localStorage 警告、构建既有 bundle 大小提示保留，不以本次迁移扩大范围修复。
- `uv run --frozen --no-sync pytest scripts/licenses/test_collectors.py`：**6 passed**。新增依赖许可按实际 METADATA/dist-info 原文更新，最终 Linux AMD64 镜像清单与扫描仍需实际构建核验。
- `sh scripts/test_deploy_reven.sh`：部署基础设施同步/恢复的隔离集成测试通过，未调用生产部署。

## 测试数据隔离

本任务只在自己新建的 `reven-agent-migration-postgres-20261006` 容器（55433）内验证。工具使用 `reven_agent_test`，入口/持久化使用 `reven_agent_entry_test`，运行时使用 `reven_agent_runtime_test`，避免并行 TRUNCATE 相互污染；两个新增测试库均从空库升级至 0028，再显式初始化 checkpoint schema 成功。用户既有 55432 PostgreSQL、生产库及旧数据卷未改动。

## 工具事务与原生恢复组合（阶段 3）

工具子代理完整集合：**211 passed in 37.11s**，数据库为本任务 `reven_agent_test`。集合包含新测试、原 CRM/Talents 工具/删除确认、领域服务/提醒、网页 CRUD 与 MCP HTTP 回路；不是只对 mock 断言调用次数。

- 37 个 native/MCP schema 共用目录，宿主 context 不出现在模型 schema，extra 注入被拒；MCP machine token 的 25 个写工具全部拒绝。
- 全部 25 写工具验证实际业务提交、提交前回滚、同 call 重放；同 call 并发只形成一条 ledger，人才画像原 call 不重复追加、新 call 可追加。
- 8 类删除测试覆盖无审批、pending、rejected、approved/consumed、重复回放及 owner/session/args/实际 target 与级联漂移；父对象 FOR UPDATE 实际阻止 FK 子项在批准窗口中插入。
- RSS pending 与账本同提交；embedding 失败保持 pending，重放补刷到 ready，没有重建关键词。
- 真实 LangGraph 与 PG 注入业务 COMMIT 后、checkpoint 前中断，重放读取历史结果；只恢复第二条 tool task 也无死锁；同批读并行/写原序、多删除决策对齐。数据库与取消异常不被伪造为普通工具成功。

19 个源文件 mypy、33 文件 format check、owned 源码/测试 ruff check、git diff --check 均通过。模型为 HTTP/确定性替身，真实上游模型仍未验证。

## SDK 退役与本机许可采集

frozen sync 实际只卸载 deepseek-harness-sdk/runtime-bin 两包，并重新安装本地 reven-server editable；既有其他版本/来源不漂移。源码/tests/锁文件不再引用 SDK、dsh_home 或旧 patch（历史文档/旧卷保留）。

`collect-runtime.py python /Users/wangyiyang/.tmp/reven-agent-licenses-20261006 licenses/supplemental/python` 收集 **131** 个本机安装包（包含开发依赖）；9 个新增运行包的锁定版本、许可原文与每项 SHA-256 均核验，清单无退役 SDK。本机 ARM64 清单未加入发布产物，也不代替最终 Linux AMD64 镜像的证据。

## 执行核心与生命周期（阶段 4）

原生服务、配置、模型切换、HITL、普通 None 恢复、提交后中断、关闭与 health 的完整 owner 集合 **59 passed in 9.98s**，隔离 `reven_agent_runtime_test`；41 源文件 mypy 和 67 文件 ruff/format 通过。新核心源码文件 ≤500 行、函数 ≤50 行。

service/model/config、审批及恢复用例覆盖原配置 revision、端点漂移/指定模型失效、历史/override、已提交工具结果重放、等待和执行期限、启动遗留扫描。独立审查复现并修复关闭竞态：旧 executor.close 的 snapshot 之后 late launch 会脱管；Service admission 收敛与 executor closing 门禁现在禁止新 launch，跨窗口已 claim 的运行持久化 interrupted/AGENT_SERVICE_CLOSING，并保留原编号。实际 service 关闭回归验证晚到 Feishu bridge 零业务效果，任务收敛。

health checks 为 db/agent/checkpointer/background_runner。db 故障返回 503；Agent/检查点降级保持 200 并显式 degraded；无模型、pool/schema 正常则 agent disabled / checkpointer ok。

## 持久化、REST、飞书与模型管理（阶段 2/5）

最终 owner 汇总 **316 passed in 90.73s**，仅使用隔离 `reven_agent_entry_test`；两个 `lark_oapi` 既有 DeprecationWarning 保留。互不重叠集合：持久化/迁移 32、chat/management 边界 36、真实 Native REST+模型删除交错 9、完整飞书/模型管理 API/Auth 239。12 源文件 mypy、31 文件 ruff/format 与范围 diff-check 通过。

- 0028 空库/存量 upgrade、ORM metadata、RLS、owner/session/FK/忙状态唯一/请求键约束及审批参数/目标漂移均验证。
- Cookie 认证成功才注入可信 admin；REST chat 两字段成功结构保持，run ID 由 header 查询，配置/历史/审批/恢复使用既有 Auth/CSRF；真实 service 实际通过 REST 跑图和工具。
- 飞书传入原 chat/open_id/message_id；确认/取消/状态/恢复确定性解析，不经模型，重查白名单；真实 native 流程同样验证。
- 模型更新 gate 双向交错测试：删除已 flush 未 commit 时新 chat 等待，删除完成后模型不可用且无 graph 执行或新运行登记；先 claim 后默认/附加模型删除均 409，terminal 后可删。gate 不覆盖模型/工具等待。
- 服务 REST wait=1000 秒时，Feishu 确认与恢复显式传自身 0.01 秒测试预算，返回原 run ID，没有先撞外层桥超时。

正式 owner 命令为明确 TEST_DATABASE_URL/DATABASE_URL 下 `.venv/bin/python -m pytest`：test_persistence、全部 migrations、API chat/management/native_flow/model_gate/integrations_agent_llm_models、全部 feishu_bot 和 security/test_auth。完整源码与后端覆盖率由独立 checker 再做总验收，以上集合存在与其他阶段重叠，不相加冒充全仓测试总数。


## GitHub Linux AMD64 全量 CI 与交付（2026-10-06）

用户明确授权“请进行处理，然后push到GitHub发起PR。”后，推送 `codex/agent-langgraph-migration` 的三个工作提交 d1d2514、b1fc2ab、5c1b89d，创建并附加 [PR #219](https://github.com/wangyiyang/Reven/pull/219)。未合并、未触发 Release and Deploy、未部署生产。

[完整 CI run 37431192893](https://github.com/wangyiyang/Reven/actions/runs/37431192893) 实际验证提交 `5c1b89d508bcab0112246a360aa84208742ba988`，workflow_dispatch `full=true`；changes、backend、migration、frontend、container 五项全部 success。

- 后端 Linux Python 3.12.13：Ruff/格式通过，Mypy 164 源文件通过，许可采集回归 6 passed；全量 **1134 passed，40 warnings，389.64 秒**，覆盖率 **90.46%**（80% 门槛）。本机曾因 SOCKS 环境失败的 URL 测试及新增空白 REST 输入回归均包含在这次真实完整运行中。
- 空库升级至 0028、原生 checkpoint 初始化与 migration 集合 **14 passed**。前端 **30 files / 247 passed**，类型检查与构建成功。
- 原生 Linux AMD64 镜像构建成功；非 root UID、只读 rootfs、Agent import、HTTP/可信 CA HTTPS/生产 Caddy 路由与静态卷验证通过。隔离 self-host 实际跑原生工具循环，完整 down/up 重建后读回原 thread 历史；日志明确出现 `Native Agent persisted history verified`，RSS 材料、活动卷与许可也通过。
- 迁移失败保留旧静态发布、发布 infra 内嵌同步/恢复、Compose/Caddy 验证通过；SBOM 生成/上传成功。Trivy 原门禁 `--ignore-unfixed --severity CRITICAL --exit-code 1` 通过，其扫描范围内 Debian/Python 可修复严重漏洞为 0；不扩展表述为所有级别漏洞均不存在。

后续改动仅补充本任务交付证据、归档和日志，不修改该已验证提交的产品代码、测试、锁文件或部署配置。真实上游模型仍未验证；没有以 mock 或成功 CI 替代该项。日志保存于本机 `/Users/wangyiyang/.tmp/reven-agent-ci-{backend,migration,frontend,container}.log`，GitHub 链接为可共享证据。
