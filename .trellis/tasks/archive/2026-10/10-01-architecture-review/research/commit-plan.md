# 三项架构改进提交方案

## 结论

按三项已独立验收的关注点提交，并单独记录领域语言。共享文件使用每项验收快照形成可独立审阅的提交；工作区保留最终实现。

验证：完整后端 787 passed / 0 skipped，coverage 90.30%；ruff、格式、strict mypy 与 500/50 行检查通过。

## 已执行提交（按确认顺序）

### 1. refactor(server): 深化 CRM 客户跟进变更入口

- [.trellis/spec/reven-server/backend/crm-contract.md](/Users/wangyiyang/Documents/Github/Reven/.trellis/spec/reven-server/backend/crm-contract.md)
- [.trellis/spec/reven-server/backend/index.md](/Users/wangyiyang/Documents/Github/Reven/.trellis/spec/reven-server/backend/index.md)
- [server/src/reven/agent/crm_tool_support.py](/Users/wangyiyang/Documents/Github/Reven/server/src/reven/agent/crm_tool_support.py)
- [server/src/reven/agent/tools_crm.py](/Users/wangyiyang/Documents/Github/Reven/server/src/reven/agent/tools_crm.py)
- [server/src/reven/agent/tools_crm_contacts.py](/Users/wangyiyang/Documents/Github/Reven/server/src/reven/agent/tools_crm_contacts.py)
- [server/src/reven/agent/tools_crm_customers.py](/Users/wangyiyang/Documents/Github/Reven/server/src/reven/agent/tools_crm_customers.py)
- [server/src/reven/agent/tools_crm_follow_ups.py](/Users/wangyiyang/Documents/Github/Reven/server/src/reven/agent/tools_crm_follow_ups.py)
- [server/src/reven/api/routes/crm.py](/Users/wangyiyang/Documents/Github/Reven/server/src/reven/api/routes/crm.py)
- [server/src/reven/api/schemas/crm.py](/Users/wangyiyang/Documents/Github/Reven/server/src/reven/api/schemas/crm.py)
- [server/src/reven/crm/errors.py](/Users/wangyiyang/Documents/Github/Reven/server/src/reven/crm/errors.py)
- [server/src/reven/crm/inputs.py](/Users/wangyiyang/Documents/Github/Reven/server/src/reven/crm/inputs.py)
- [server/src/reven/crm/service.py](/Users/wangyiyang/Documents/Github/Reven/server/src/reven/crm/service.py)
- [server/tests/agent/test_tools_crm.py](/Users/wangyiyang/Documents/Github/Reven/server/tests/agent/test_tools_crm.py)
- [server/tests/api/test_crm.py](/Users/wangyiyang/Documents/Github/Reven/server/tests/api/test_crm.py)
- [server/tests/crm/test_service.py](/Users/wangyiyang/Documents/Github/Reven/server/tests/crm/test_service.py)

### 2. refactor(server): 统一飞书消息交付

- [.trellis/spec/reven-server/backend/feishu-app-notification-contract.md](/Users/wangyiyang/Documents/Github/Reven/.trellis/spec/reven-server/backend/feishu-app-notification-contract.md)
- [server/src/reven/app.py](/Users/wangyiyang/Documents/Github/Reven/server/src/reven/app.py)
- [server/src/reven/integrations/feishu_bot/chat_dispatcher.py](/Users/wangyiyang/Documents/Github/Reven/server/src/reven/integrations/feishu_bot/chat_dispatcher.py)
- [server/src/reven/integrations/feishu_bot/client.py](/Users/wangyiyang/Documents/Github/Reven/server/src/reven/integrations/feishu_bot/client.py)
- [server/src/reven/integrations/feishu_bot/handlers.py](/Users/wangyiyang/Documents/Github/Reven/server/src/reven/integrations/feishu_bot/handlers.py)
- [server/src/reven/integrations/feishu_bot/supervisor.py](/Users/wangyiyang/Documents/Github/Reven/server/src/reven/integrations/feishu_bot/supervisor.py)
- [server/src/reven/notify/notifier.py](/Users/wangyiyang/Documents/Github/Reven/server/src/reven/notify/notifier.py)
- [server/src/reven/notify/scheduler.py](/Users/wangyiyang/Documents/Github/Reven/server/src/reven/notify/scheduler.py)
- [server/src/reven/provider_clients.py](/Users/wangyiyang/Documents/Github/Reven/server/src/reven/provider_clients.py)
- [server/tests/integrations/feishu_bot/test_app_lifespan.py](/Users/wangyiyang/Documents/Github/Reven/server/tests/integrations/feishu_bot/test_app_lifespan.py)
- [server/tests/integrations/feishu_bot/test_chat_dispatcher.py](/Users/wangyiyang/Documents/Github/Reven/server/tests/integrations/feishu_bot/test_chat_dispatcher.py)
- [server/tests/integrations/feishu_bot/test_client.py](/Users/wangyiyang/Documents/Github/Reven/server/tests/integrations/feishu_bot/test_client.py)
- [server/tests/integrations/feishu_bot/test_handlers.py](/Users/wangyiyang/Documents/Github/Reven/server/tests/integrations/feishu_bot/test_handlers.py)
- [server/tests/integrations/feishu_bot/test_model_commands.py](/Users/wangyiyang/Documents/Github/Reven/server/tests/integrations/feishu_bot/test_model_commands.py)
- [server/tests/notify/test_notifier.py](/Users/wangyiyang/Documents/Github/Reven/server/tests/notify/test_notifier.py)
- [server/tests/notify/test_scheduler.py](/Users/wangyiyang/Documents/Github/Reven/server/tests/notify/test_scheduler.py)
- [server/tests/notify/test_scheduler_delivery.py](/Users/wangyiyang/Documents/Github/Reven/server/tests/notify/test_scheduler_delivery.py)
- [server/tests/test_provider_clients.py](/Users/wangyiyang/Documents/Github/Reven/server/tests/test_provider_clients.py)

### 3. refactor(server): 集中会话模型选择与生效身份

- [.trellis/spec/reven-server/backend/agent-dsh-contract.md](/Users/wangyiyang/Documents/Github/Reven/.trellis/spec/reven-server/backend/agent-dsh-contract.md)
- [.trellis/spec/reven-server/backend/feishu-app-notification-contract.md](/Users/wangyiyang/Documents/Github/Reven/.trellis/spec/reven-server/backend/feishu-app-notification-contract.md)
- [docs/agent-architecture.md](/Users/wangyiyang/Documents/Github/Reven/docs/agent-architecture.md)
- [server/src/reven/agent/service.py](/Users/wangyiyang/Documents/Github/Reven/server/src/reven/agent/service.py)
- [server/src/reven/api/dependencies.py](/Users/wangyiyang/Documents/Github/Reven/server/src/reven/api/dependencies.py)
- [server/src/reven/api/routes/agent.py](/Users/wangyiyang/Documents/Github/Reven/server/src/reven/api/routes/agent.py)
- [server/src/reven/app.py](/Users/wangyiyang/Documents/Github/Reven/server/src/reven/app.py)
- [server/src/reven/integrations/feishu_bot/chat_dispatcher.py](/Users/wangyiyang/Documents/Github/Reven/server/src/reven/integrations/feishu_bot/chat_dispatcher.py)
- [server/src/reven/integrations/feishu_bot/commands.py](/Users/wangyiyang/Documents/Github/Reven/server/src/reven/integrations/feishu_bot/commands.py)
- [server/tests/agent/test_runtime.py](/Users/wangyiyang/Documents/Github/Reven/server/tests/agent/test_runtime.py)
- [server/tests/agent/test_service.py](/Users/wangyiyang/Documents/Github/Reven/server/tests/agent/test_service.py)
- [server/tests/agent_service_support.py](/Users/wangyiyang/Documents/Github/Reven/server/tests/agent_service_support.py)
- [server/tests/api/test_agent_chat.py](/Users/wangyiyang/Documents/Github/Reven/server/tests/api/test_agent_chat.py)
- [server/tests/integrations/feishu_bot/test_app_lifespan.py](/Users/wangyiyang/Documents/Github/Reven/server/tests/integrations/feishu_bot/test_app_lifespan.py)
- [server/tests/integrations/feishu_bot/test_chat_dispatcher.py](/Users/wangyiyang/Documents/Github/Reven/server/tests/integrations/feishu_bot/test_chat_dispatcher.py)
- [server/tests/integrations/feishu_bot/test_model_commands.py](/Users/wangyiyang/Documents/Github/Reven/server/tests/integrations/feishu_bot/test_model_commands.py)

### 4. docs: 记录架构领域语言

- [GLOSSARY.md](/Users/wangyiyang/Documents/Github/Reven/GLOSSARY.md)

## 原有现场与收尾

- 用户原有 uv.lock 改动保留在工作区，不纳入上述提交；SHA256 与实施前一致。
- 上述工作提交完成后，按 Trellis 流程归档本轮父任务及三个子任务，并记录会话；脚本分别产生任务归档和日志提交。
- 本轮不推送远端；没有 PR 创建或部署步骤。

## 确认依据

仓库 .trellis/workflow.md 第3.4阶段要求："Present the plan once, ask for one-shot confirmation"。整批实施已获授权，此处仅确认具体提交分组及随后收尾。

## 执行记录

用户已确认整批方案。

- `cc10725c`：refactor(server): 深化 CRM 客户跟进变更入口
- `40c2f303`：refactor(server): 统一飞书消息交付
- `501fcffe`：refactor(server): 集中会话模型选择与生效身份
- `2940ef26`：docs: 记录架构领域语言
