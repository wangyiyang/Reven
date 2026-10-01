# 飞书消息交付独立核查结果

## 结论

本项独立核查通过，未发现需要修复或留待决策的问题。可以按已批准顺序开始会话模型子任务；三项完成后的整套后端集成验证仍由主线程执行。本次未改动生产代码、测试、spec、任务状态、CRM 或 uv.lock，未提交或 push。

## Findings (fixed)

无。实现符合本项 PRD、design、implement 与相关后端契约，lint/type-check 实际验证通过。

## Findings (not fixed)

无。本次没有需要扩大任务范围、改变公共接口或重新决定模块边界的问题。

## 行为复核

- AC1：`FeishuBotApiClient._deliver` 是唯一同目标卡片→文本策略。open_id、chat_id、reply 在同一 HTTP seam 上参数化验证卡片成功、业务错误、HTTP 错误、非法响应、ConnectError/ReadTimeout、两次失败及脱敏。普通 markdown 文本前置标题并保留原正文；结构化 Notification 保留 title/stage/summary/label：URL。多人部分失败继续尝试所有接收人并整体报错。
- AC2：reply 的编码路径保留原 message_id，Bearer tenant token 与本地安装 SDK 的协议相符；payload 仅 msg_type/content，不带 receive_id/type、uuid 或 reply_in_thread。SDK handler 只路由并 submit，所有外显回复通过既有 bridge 回主循环；`_send_reply` 返回 True 区分成功与 None 失败。白名单预检先于所有回复，占位失败零 Agent，dead loop/调度失败关闭协程，120s 对话超时不取消的机制保持。
- AC3：主动 chat 的卡片和文本均失败后才尝试白名单；文本成功仍返回 chat 渠道。引用回复没有跨目标渠道。CRM 提醒→调度器→真实 FeishuProactiveNotifier→MockTransport 的组合回归确认文本保留标题、客户名、事项和到期信息。
- AC4：FeishuReplier 每次经 ProviderClients 现读配置/凭证，复用共享 AsyncClient；替换凭证或禁用后下一次回复生效。handlers 的 SDK 出站 client/闭包及重复策略已删除，SDK 保留 WS 入站。supervisor 的 bot_open_id、reload、代际循环未改写。app 生命周期拆分保持启动、清理、内外部 factory 归属与主异常优先级，并有原故障回归验证。

当前主线程同步的飞书契约已准确描述新签名、内容保留、目标与渠道降级、异步 replier 和桥接纪律，无额外文档差异。send_text/send_text_to_recipients 的连接测试用途仍保留；删除孤儿 send_text_to_chat 不构成契约缺口。

## Verification

测试均使用主线程准备的专用测试库与 MockTransport/respx，不触真实飞书或 LLM：

```sh
.venv/bin/python /Users/wangyiyang/.tmp/reven-architecture-test-run.py uv run --frozen pytest server/tests/integrations/feishu_bot server/tests/notify server/tests/integration/test_feishu_notification_contract.py server/tests/test_provider_clients.py server/tests/test_background.py -W error::RuntimeWarning
# 192 passed / 0 skipped，14.77s；仅两个既有 lark SDK DeprecationWarning
.venv/bin/python /Users/wangyiyang/.tmp/reven-architecture-test-run.py uv run --frozen pytest server/tests/test_health.py server/tests/integrations/test_credentials.py -W error::RuntimeWarning
# 39 passed / 0 skipped，3.34s
uv run --frozen ruff check server
# All checks passed!
uv run --frozen ruff format --check server
# 252 files already formatted
uv run --frozen mypy server/src
# Success: no issues found in 130 source files
git diff --check
# 通过
```

AST 与行数核对：本项八个生产文件全部 <=500 行，最大文件 app.py 为334行；全部函数 <=50行，最大函数 `_run_app_resources` 为46行。代码搜索未发现遗留 fallback_text 调用、SDK reply 构造或旧同步 reply 接线。

用户现场 uv.lock SHA256 保持 `9a16e44a1a009b119257576de69ce5c9a6b91c115259d4fa29028068d26587d7`。
