# 执行：飞书消息交付

前置：父任务整批方案已批准；10-01-crm-deepening 实现与验证先完成，按用户顺序开始本项。共享文件基于已完成结果修改，不恢复旧接线。

1. 增 HTTP reply 请求形状、网络异常/业务码降级与标题保留回归，再在既有 client 集中 _deliver。
2. 迁移结构化 Notification 和主动通知调用，删除调用方 fallback_text；区分同目标降级和跨渠道选择。
3. 注入 FeishuReplier，经原 bridge 回主循环发送；迁移 submit / handler / supervisor / app 装配，删除 SDK 出站闭包。
4. 替换重复策略测试，保留白名单、guide/unsupported、占位、timeout、dead loop 与连接生命周期断言。
5. trellis-check 验证并修复，回写飞书契约；本项通过后才开始会话模型子任务。

验证（专用测试库；不真实给用户发送飞书消息）：

```sh
uv run --frozen pytest server/tests/integrations/feishu_bot server/tests/notify server/tests/integration/test_feishu_notification_contract.py server/tests/test_provider_clients.py server/tests/test_background.py -W error::RuntimeWarning
uv run --frozen ruff check server
uv run --frozen ruff format --check server
uv run --frozen mypy server/src
```

核对 reply 目标与引用、标题/正文、多人部分失败、循环所有权和凭证现读；函数 <=50、文件 <=500；禁止在 SDK handler 等慢 IO 或创建新循环。

提交关注点：refactor(server): 统一飞书消息交付。完成验证后核对实际文件，不纳入用户现场。
