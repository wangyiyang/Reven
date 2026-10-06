# 独立质量审查（2026-10-06）

审查依据为 `check.jsonl` 的实际条目及 PRD/design/implement。范围覆盖 Agent 配置/会话/运行、检查点与恢复、25 个写工具及 8 个删除审批、REST/飞书认证与等待、迁移/只读部署触点；前端与 Linux AMD64 full CI 由主代理验证。

## 发现与修复

1. **关闭时晚到任务丢失生命周期管理**：原 `RunExecutor.close()` 先复制任务，再等待取消；此时 `launch()` 能启动新任务，随后 `tasks.clear()` 丢失仍运行的任务。独立无数据库复现得到 `late_task_still_running=True`、`late_task_still_owned=False`。与运行时负责人协作修复：服务关闭门禁覆盖短 admission 的 claim/decision 到 launch；跨关闭窗口已认领的运行持久化 `interrupted/AGENT_SERVICE_CLOSING`，保留原编号；执行器先设关闭标志，再收敛既有任务，构造协程前拒绝新 launch。独立复测拒绝码正确、任务表为空；真实服务竞争回归由运行时负责人完成。
2. **飞书批准/恢复等待预算未传入服务**：原 chat 已传 dispatcher 预算，批准/恢复却使用应用默认等待预算。应用配置超过外层桥预算时会先返回通用兜底。主代理确认后，由运行时与入口负责人增加可选 `wait_timeout_seconds`，飞书明确传入，REST 默认与成功 JSON 保持。实际服务与飞书组合覆盖长应用等待预算和短入口预算，返回原运行编号。
3. **未知工具配置错误码混同状态冲突**：原未知工具返回 `409 AGENT_STATE_CONFLICT`。按主代理决策改为 `422 AGENT_TOOL_UNKNOWN`，拒绝无效配置并保持版本/执行不新增；原运行恢复的禁用/漂移错误继续保持其独立语义。
4. **迁移产生的孤儿常量与格式**：移除无调用的 `DEFAULT_AGENT_MCP_URL`；审查代理仅对 `agent/__init__.py` 补缺少的空行。
5. **纯空白 REST 输入被误报上游故障**：真实服务对纯空白输入抛 `AGENT_INPUT_INVALID`，路由缺少状态映射，实际返回 `502`。先新增真实 REST 回归复现，再按主代理批准映射至 `422`；成功 JSON 保持原状。回归核对无新增会话、运行、执行任务或模型调用。
6. **既有 RSS URL 校验测试读取宿主代理**：全量唯一失败发生于 `httpx.AsyncClient` 构造，因本机 SOCKS 代理要求未安装的可选 `socksio`，尚未进入 URL 校验。仅在该测试的两处客户端设 `trust_env=False`，保留 HTTPS/localhost 断言，不修改生产 RSS 或依赖。RSS 全集合随后通过。

## 源码核验

- 请求去重按可信 owner/channel/request_key 隔离；缺 session_id 的同键重发附着原运行，同键不同输入/明确不同 session 冲突；业务相同但不同键仍可新建。
- 写入口在同一事务锁定运行、核对 owner/session/call/tool/参数，保存业务结果并消费批准；CRM/Talents 通过 `commit=False` 参与，网页默认提交保持。RSS 后置 embedding 只补刷已保存 ID。
- 删除审批同时检查规范化参数与实际目标指纹；执行端锁定父项及相关子项复核，机器 MCP 的全部写操作拒绝。原批次后序恢复复用前序已提交结果，不等待不会重调度的任务。
- 恢复使用原 revision/model/公开快照及匹配的 checkpoint metadata/HumanMessage；普通续接和 HITL Command 分开，缺安全依据标为待核实，未发现盲目重跑原输入的路径。
- 密钥只通过既有凭据 seam 解密；运行快照无密钥，模型错误边界脱敏，禁用外部 tracing；serializer 明确禁止任意类型与 pickle 回退。
- 0028 和 ORM/metadata/fixture 清表触点一致；entrypoint 在静态切换前执行 Alembic/checkpoint 初始化，活动 Compose 不依赖 DSH 卷或可写 HOME，旧卷保留说明齐全。

## 独立验证

- `ruff check server`：通过。
- `ruff format --check server`：332 文件通过。
- `mypy server/src`：164 文件通过。
- `git diff --check`：通过。
- 隔离测试库已核验为 `reven_agent_test`，仅使用 localhost:55433；版本为 `0028_agent_persistence`，框架 checkpoint schema 已初始化。
- 首次全量 `pytest server/tests --cov=reven --cov-report=term-missing --cov-fail-under=80`：**1132 passed、1 failed**，236.92 秒；覆盖率 **90.41%**，达到 80% 门槛。唯一失败为上述宿主代理影响的 RSS URL 校验，已定向修复。这是该次完整运行的测量，未将后续补测合并成一次全量计数。
- 修复后的 `pytest server/tests/rss server/tests/api/test_agent_native_flow.py -q`：**93 项全部通过**（RSS 86、真实 REST 7），包括新增纯空白输入回归；未调用外部模型。该次进程退出码为 0，单独 `--collect-only` 核对 93 项。
- 最后修改的三文件重新运行 Ruff/格式均通过；`mypy server/src/reven/api/routes/agent.py` 通过；最终 `git diff --check` 通过。
- 全量日志为 `/Users/wangyiyang/.tmp/reven-agent-full-pytest.log`，覆盖率 JSON 为 `/Users/wangyiyang/.tmp/reven-agent-coverage.json`；补测日志为 `/Users/wangyiyang/.tmp/reven-agent-focused-final.log`。

## 未修复发现与验证边界

未保留已确认的正确性问题。本机没有无差别重复全量；当前完整集合由主代理的 Linux AMD64 full CI 再验证。独立审查发现的关闭竞态、等待预算、未知工具状态已协作修复，并纳入首次全量；后续两个局部修改经过上述定向集合与静态复测。

本审查未访问生产数据库、既有 55432 数据库或其他代理的测试库；不提交、不推送。真实上游模型与原生 Linux AMD64 镜像验收属于单独证据，不能由 PostgreSQL/确定性模型测试替代。
