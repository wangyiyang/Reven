# 飞书消息交付实施结果

本项已完成实施与针对性验证，待主线程独立 trellis-check。未提交或 push；未修改 CRM、会话模型语义、spec、GLOSSARY、任务规划或 uv.lock。

## 结果

- FeishuBotApiClient 的唯一 `_deliver` 负责同目标 interactive→text。新增 `reply_markdown` 与结构化 `send_notification_to_recipients`；普通 markdown 文本自动前置标题，Notification 文本保持 title/stage/summary/label：URL。
- 引用回复使用编码后的原 message_id 路径，body 仅 msg_type/content，复用 tenant token 和现有脱敏 HTTP 错误；卡片业务、HTTP、非法响应和网络失败均尝试文本，两次失败明确传播。
- ProviderClients.FeishuReplier 每次读取当前配置/凭证并复用共享 httpx。handlers 删除 SDK 出站 client/闭包，SDK 仅 WS 入站，dispatcher 构造注入异步 reply，submit 不再携带 reply。
- 所有回复经既有 `_bridge` 回主循环；`_send_reply` 成功返回 True 区别 None 失败哨兵。保持白名单先行、占位失败零 Agent、120s 超时不取消、指令/引导/非文本直接回复与连接代际规则。
- 主动通知仅在定向 chat 卡片与文本都失败后才改投白名单；引用回复始终只针对同一 message_id。
- app 原 `_lifespan` 67 行拆分为装配与 `_run_app_resources` 的启动/清理职责，保持资源归属、异常优先级和清理顺序，为后续共享 AgentService 保留装配位置。
- 删除因统一 `_deliver` 成为孤儿的 `send_text_to_chat`；保留连接测试使用的 send_text/send_text_to_recipients。

## 文件

生产：

- server/src/reven/integrations/feishu_bot/{client,chat_dispatcher,handlers,supervisor}.py
- server/src/reven/provider_clients.py
- server/src/reven/app.py
- server/src/reven/notify/{notifier,scheduler}.py

测试：

- server/tests/integrations/feishu_bot/{test_client,test_chat_dispatcher,test_handlers,test_model_commands,test_app_lifespan}.py
- server/tests/test_provider_clients.py
- server/tests/notify/{test_notifier,test_scheduler,test_scheduler_delivery}.py（最后一个为新增组合测试）

迁移测试删除旧 SDK 出站 fake 与重复 card/text 策略，HTTP 测试按 open_id/chat_id/reply 参数化；保留 handler 路由矩阵和原指令语义。

## 实际验证

DB 命令均经专用测试环境 runner，未使用用户现有业务库，未发送真实飞书或 LLM 消息：

```sh
.venv/bin/python /Users/wangyiyang/.tmp/reven-architecture-test-run.py uv run --frozen pytest server/tests/integrations/feishu_bot server/tests/notify server/tests/integration/test_feishu_notification_contract.py server/tests/test_provider_clients.py server/tests/test_background.py -W error::RuntimeWarning
# 最终 192 passed / 0 skipped，14.83s（迁移首轮187 passed，补完新增行为后为192）
.venv/bin/python /Users/wangyiyang/.tmp/reven-architecture-test-run.py uv run --frozen pytest server/tests/integrations/test_credentials.py -W error::RuntimeWarning
# 29 passed / 0 skipped，2.80s
.venv/bin/python /Users/wangyiyang/.tmp/reven-architecture-test-run.py uv run --frozen pytest server/tests/test_health.py -W error::RuntimeWarning
# 10 passed / 0 skipped，0.73s，覆盖生命周期拆分的启动失败/清理归属/错误优先级
uv run --frozen ruff check server
# All checks passed（首轮发现删除 SDK 测试后留下的 json import，已移除并复验通过）
uv run --frozen ruff format --check server
# 252 files already formatted
uv run --frozen mypy server/src
# Success: no issues found in 130 source files
git diff --check
# 通过
```

新增行为断言：主循环所有权、async reply 等待时 submit 返回、reply 调度失败关闭未 await 协程、占位失败零 Agent、凭证替换与禁用下一次回复生效、chat 文本成功不改投白名单、CRM 提醒→scheduler→真实 FeishuProactiveNotifier→MockTransport 的文本标题/客户/事项/到期信息完整。

本项生产文件最大334行（app.py），函数最大46行（_run_app_resources）；本项测试文件最大402行。用户 uv.lock SHA256 保持 `9a16e44a1a009b119257576de69ce5c9a6b91c115259d4fa29028068d26587d7`。

## 剩余事项与风险

- 主线程仍需独立 check 和三项完成后的整套后端集成验证；本项未提前实施会话模型状态迁移。
- 测试有两个既有 lark SDK DeprecationWarning（protobuf 的 utcfromtimestamp、SDK import 的 get_event_loop）；没有 RuntimeWarning 或 skip。
- 当轮更换应用凭证可能使旧 message_id 无法回复，按固定脱敏失败收敛，不使用旧密钥、不改投其他接收人；保留批准设计的既有超时不取消取舍。
