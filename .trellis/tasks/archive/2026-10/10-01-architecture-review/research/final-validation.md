# 三项架构深化最终整体验收

结论：CRM、飞书消息交付、会话模型身份已按顺序完成实现与独立核查；本次最终 check 覆盖三项合并后的全后端范围，结果通过，可进入工作提交与交付。产品与测试没有新发现；文档中的两组表述偏差已由主线程按反馈修正并复核，没有未解决发现。

## 实际门禁结果

| 检查 | 结果 |
| --- | --- |
| 全后端 pytest（含真实 PostgreSQL 与 dsh smoke） | 787 passed，0 skipped，18 warnings，98.95s |
| Coverage | 90.30%，达到 80% 门禁 |
| ruff check server | 通过 |
| ruff format --check server | 通过，254 files already formatted |
| strict mypy server/src | 通过，130 source files |
| git diff --check | 通过，文档修正后再次通过 |
| 本批 Python 规模 | 38 个变更文件全 <=500 行，全部函数 <=50 行；最大文件 466 行，最长函数 46 行 |
| uv.lock 原改动保护 | SHA256 与执行基线相同 |

命令在仓库根运行；数据库测试仅使用主线程建立并迁移至 head 的专用库，检查代理执行时独占该库。所有 uv 命令使用 `--frozen`：

```sh
.venv/bin/python /Users/wangyiyang/.tmp/reven-architecture-test-run.py uv run --frozen pytest server/tests --cov=reven --cov-report=term-missing --cov-fail-under=80
uv run --frozen ruff check server
uv run --frozen ruff format --check server
uv run --frozen mypy server/src
git diff --check
```

完整日志：`/Users/wangyiyang/.tmp/reven-architecture-final-pytest.log`。
规模证据：`/Users/wangyiyang/.tmp/reven-architecture-final-size-check.json`。
uv.lock：`9a16e44a1a009b119257576de69ce5c9a6b91c115259d4fa29028068d26587d7`。

18 条 warning 均来自既有使用：lark-oapi 2 条、旧 HTTP 422 常量 2 条、SQLAlchemy 的旧 utcnow 14 条，没有 RuntimeWarning。不为这些无关弃用提示扩展本任务。

## 全范围行为与兼容性

- CRM：领域 inputs + 业务 ID 的九个完整写操作拥有客户范围、查找、固定错误、合并后计划校验与提交；REST/MCP 写入口不再预查 ORM。`exclude_unset` 保留 partial/null 区别；主联系人切换、历史/当前计划一次提交及快照规则通过。只关联/解除跟进联系人回归与真实 MCP 调用通过；前项独立比较的六个输入/三个响应 schema、十五个工具完整协议保持，第三项没有再改 CRM。
- 飞书：唯一 HTTP `_deliver` 覆盖 open_id/chat_id/reply 的卡片→同目标文本。reply 保留编码 message_id、tenant token 和仅 msg_type/content 的 body；业务、HTTP、网络与格式错误均按同一失败策略处理，两次失败脱敏。普通正文保留标题，Notification 保留阶段/摘要/链接。主动 chat 两次失败才走白名单；CRM 提醒→scheduler→真实 notifier→MockTransport 的组合内容回归通过。
- 入站与装配：SDK handler 只路由/submit 立即返回，异步回复和 Agent 都桥回主循环；白名单先于任何回复，`True` 成功哨兵、占位失败零 Agent、调度失败 close 协程、120s 超时不取消均保留。每次回复现读凭证，复用 ProviderClients 共享 HTTP。前项 lifespan 拆分与本项共享 AgentService 接线共同保持故障资源归属、清理顺序和主异常优先级。
- 会话模型：同 app 的 REST/飞书共享唯一业务对象，不同 app/重启独立；模型选择仍按 IM 外部会话 ID，回答使用执行前捕获的 frozen 结果。启动默认与保存默认区分、A 移除后恢复、B 的 override 不误清、禁用/未知/失败保留选择且不回落、执行中切换不误标均在真实 service/runtime + fake harness 的同一业务 seam 验证。
- 运行时：runtime/config 产品机制没有修改，resolver、池/局部锁、别名及一次重试、启动降级、无 resume、无全局锁保留。完整 suite 实际包含 `_harness is not None` 的真实 initialize/close smoke 和 dsh `--dump-config` patch 测试，均通过，无环境跳过。

## Findings (fixed)

1. 飞书契约原错误矩阵把所有 AgentError 写作通用兜底；主线程已区分 `AgentModelUnavailableError` 的明确提示、保留选择与显式恢复路径。
2. Agent 维护说明仍写唯一 dsh 实例和全部配置仅启动读取；主线程已澄清默认主实例 + per-ref 惰性池，默认及已有池参数需重启、指定模型可用性每轮现读，并同步 Agent 契约配置节。检查代理已复核具体回写，没有产品代码变更，因此无需重复完整 suite。

## Findings (not fixed)

无。没有需要产品判断、公共接口调整或超出批准范围的阻断问题。

## 验收与交付边界

父任务 AC1–AC5 的产品行为和质量证据已齐；AC6 的领域/契约同步与 uv.lock 保护已核对，原子提交、PR、归档/journal 仍由主线程按项目结束流程处理。检查代理未提交、push、部署或修改任务状态。

未发送真实飞书消息或 LLM prompt。fake harness 的模型身份测试、真实 dsh 握手和 patch 测试各自验证所述边界，不代表线上外部服务可达性或共享磁盘历史的额外承诺。默认与池参数不热重建、会话选择重启丢失、超时后 dsh 不取消仍为批准保留的既有行为。
