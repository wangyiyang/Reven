# 执行：会话模型身份

前置：父任务整批方案已批准；10-01-feishu-delivery-deepening 实现与验证通过。dispatcher/app 已有第二项交付，必须基于其结果迁移，不恢复旧 reply 策略。

1. 在真实 AgentService/runtime + fake harness 的业务 seam 复现模型选择与默认漂移，设计公开结果断言。
2. 深化 AgentService 并建立 startup 共享生命周期，迁移 REST 接线保持 JSON 和错误码。
3. 迁移飞书模型状态与落款，删除旧 override / registry 默认判断，保留 IM 语法与会话映射。
4. 覆盖切换→实际模型→恢复→重铸后继续、禁用后严格失败、默认漂移和执行中切换身份；更新装配与既有 adapter 测试。
5. trellis-check 验证，回写 Agent / 飞书契约及维护说明；父任务进行三项完整集成检查。

验证（专用测试库；fake harness 不产生真实 LLM 消费）：

```sh
uv run --frozen pytest server/tests/agent server/tests/integrations/feishu_bot server/tests/integrations/test_agent_model_registry.py server/tests/api/test_agent_chat.py -m 'not dsh_runtime' -W error::RuntimeWarning
uv run --frozen ruff check server
uv run --frozen ruff format --check server
uv run --frozen mypy server/src
uv run --frozen pytest server/tests/agent/test_runtime.py -m dsh_runtime
```

真实 dsh 握手环境如不支持，明确报告未验证并保留 fake 行为结果；不把 skip 当通过。最后一项是既有握手 smoke，不调用真实 LLM。

核对同一 app 的 REST / 飞书共用业务对象、不同 app 不共享选择、实际默认与保存默认区分、strict override 不回落、函数/文件长度；禁止新增持久化、全局锁、resume 或改别名键。

提交关注点：refactor(server): 集中会话模型身份。完成后核对实际文件与父任务三项最终验证。
