# 会话模型身份独立验收结果

结论：第三项通过，三项合并后的后端整体验收也通过。未发现需要修复的生产代码或测试问题；本代理没有改动产品、测试、任务状态或 uv.lock，没有提交或 push。

## Findings (fixed)

- File：`.trellis/spec/reven-server/backend/feishu-app-notification-contract.md`
  - Issue：错误矩阵把全部 AgentError 描述为通用兜底，与 `_chat` 对 `AgentModelUnavailableError` 的明确提示不一致。
  - Fix：主线程按本次反馈区分超时/其他 AgentError 与指定模型不可用；保留选择、不回落及恢复提示已明确。检查代理复核回写结果。
- File：`docs/agent-architecture.md`、`.trellis/spec/reven-server/backend/agent-dsh-contract.md`
  - Issue：维护说明仍写唯一 dsh 实例、全部配置仅在启动时读取，不能准确描述已有默认主实例和模型池，也会混淆默认启动快照与指定模型可用性现读。
  - Fix：主线程更新开篇、架构图、职责表、配置与限制说明：默认主实例 + per-ref 惰性池；默认及已启动实例参数需重启，指定模型可用性每轮现读。检查代理复核回写结果。未因此修改 runtime/config 机制。

## Findings (not fixed)

无。没有未解决的任务内问题、公共契约或模块边界决策。

## Verification

- Affected packages：通过 `python3 .trellis/scripts/get_context.py --mode packages` 核对，实际变更仅 `reven-server` 后端；已读 backend/index、质量、CRM、飞书、Agent、Provider、数据库与相关共享指南。没有前端变更。
- Lint：通过，`uv run --frozen ruff check server` → `All checks passed!`。
- Format：通过，`uv run --frozen ruff format --check server` → 254 files already formatted。
- TypeCheck：通过，`uv run --frozen mypy server/src` → 130 source files 无问题（strict 配置）。
- Tests：完整最终状态通过，专用数据库 runner 执行 `uv run --frozen pytest server/tests --cov=reven --cov-report=term-missing --cov-fail-under=80` → **787 passed，0 skipped，18 warnings，98.95s**；覆盖率 **90.30%**，高于 80% 门禁。
- 真实 dsh：完整 suite 没有排除 `dsh_runtime`；真实 initialize/close smoke 的 `_harness is not None` 断言通过，真实 `--dump-config` patch 组合测试也通过。没有将 configured 或 skip 当作握手成功，没有发送真实 LLM prompt 或飞书消息。
- Warnings：两个既有 lark-oapi DeprecationWarning、两个旧 HTTP 422 常量的 StarletteDeprecationWarning、十四个 SQLAlchemy 调用旧 utcnow 的 DeprecationWarning；没有 RuntimeWarning。
- Diff：`git diff --check` 通过，主线程文档修正后再次通过。
- 规模：本批 38 个变更 Python 文件全部 <=500 行，全部函数 <=50 行；最大文件 466 行（CRM MCP 测试），最长函数 46 行（`_run_app_resources`）。
- 用户现场：uv.lock SHA256 保持 `9a16e44a1a009b119257576de69ce5c9a6b91c115259d4fa29028068d26587d7`。

完整日志：`/Users/wangyiyang/.tmp/reven-architecture-final-pytest.log`。
逐文件规模结果：`/Users/wangyiyang/.tmp/reven-architecture-final-size-check.json`。

## 第三项真实路径复核

- lifespan 在所有降级形态也创建 `app.state.agent_service`；飞书 dispatcher 与 REST 依赖复用同一对象，缺失对象显式失败，不再按请求新建。不同 app 和模拟重启拥有独立选择；REST 请求、响应字段、鉴权与已有错误映射保留。
- `SessionModelState`、`AgentTurn` 为 frozen/slots dataclass，只带模型 ref、事实与响应，没有凭证。选择以调用方外部 session_id 为键；runtime 重铸后的活跃 ID 不替换选择键，飞书只拥有 IM ID 映射、语法与渲染。
- 生效默认来自 runtime 启动配置。保存默认 A→B 不热换主实例；use B 仍为 override，use A 才恢复，即使 A 已从注册表消失也可恢复。未知/禁用选择拒绝且原选择保留；已选模型失效或调用失败不回默认。
- `chat` 在进入 runtime 前捕获 override 与本轮 ref。事件控制的真实 service/runtime + fake harness 组合验证执行中切回默认后，已开始回答仍标原模型，下一轮才采用默认。
- runtime/config 生产文件没有修改；`resolve_agent_model_config`、每轮可用性检查、per-ref 懒启动锁、模型池复用与关闭、别名冲突一次重试、主实例启动失败先决条件、无 resume 与无全局锁均保留并回归通过。新增测试观察 fake adapter 的实际模型调用及公开业务结果，没有复制选择状态机。

## 验证边界

fake harness 验证业务选择和调用身份，真实 dsh 测试验证初始化/关闭与 patch 组合；没有把这些结果扩展为上游真实 LLM、共享磁盘历史或线上飞书可达性的实测。会话选择仍是进程内状态、参数变更仍按既定重启规则、对话超时仍不取消 dsh，均为本次批准保留的取舍。
