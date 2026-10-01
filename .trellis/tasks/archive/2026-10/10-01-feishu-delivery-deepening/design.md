# 设计：飞书消息交付 module

## 结论

深化既有 FeishuBotApiClient，在同一 httpx transport 后提供通知与引用回复；删除 handlers 的 SDK 出站 client 和重复降级，SDK 保留 WS 入站。

## 出站 interface 与内容

- send_markdown / send_markdown_to_chat / send_markdown_to_recipients 不再要求 fallback_text。
- reply_markdown(message_id, markdown, title=None) 使用 POST /open-apis/im/v1/messages/{编码后的 message_id}/reply；msg_type/content 与原引用请求一致，不增加 uuid/reply_in_thread。
- send_notification_to_recipients 接收既有 Notification，由出站 module 生成卡片与纯文本，保持阶段、摘要和 label：URL 文本格式。
- 一份私有 _deliver 实现 interactive→text，复用 _request 的鉴权、网络/业务错误映射和脱敏。
- 普通 markdown 的文本表示保留原正文并前置非空标题；不新增任意 Markdown parser。

## 调用与生命周期

ProviderClients 中的异步 FeishuReplier 复用现读凭证和共享 HTTP；通知 adapter 不再自己拼两份正文。dispatcher 构造注入异步 reply callable；handlers submit 只带 kind / message / chat / sender / text，立即返回。

所有回复在 daemon 中通过既有 _bridge 回主循环执行。_send_reply 成功返回 True，区分 reply 的 None 成功值与 bridge 的 None 失败哨兵。占位成功后才执行 Agent，调度失败关闭协程，不新建 event loop 或 AsyncClient。

app/supervisor 只迁移装配签名；WS 鉴权、bot_open_id、群 @、代际连接和 reload 机制保留。每次出站从 clients.feishu_bot() 现读 enabled / 凭证；没有可用 client 明确失败。

## 不变量与错误

- 白名单预检在任何外显回复之前；非白名单零发送零 Agent。
- 同目标卡片失败（业务码、HTTP、网络、非法响应）尝试文本；两次失败脱敏抛出，不报成功。
- reply 两次都只引用原 message_id，绝不改投白名单。
- 定向 chat 的卡片与文本都失败后，ProactiveNotifier 才沿既有渠道规则尝试白名单；单次卡片失败不得触发改投。
- 保留原占位/最终顺序、guide/unsupported/命令直接回复、120s 模型超时不取消与多人部分失败纪律。

## 测试与取舍

HTTP client seam 参数化 open_id/chat_id/reply 目标请求与失败矩阵，策略只有一套测试；删除 SDK 出站 fake 的重复策略测试。dispatcher 只验证主循环、即时 submit、白名单、dead loop、占位失败、timeout 与收敛行为。

增一条 CRM 提醒→调度器→真实主动通知 adapter→MockTransport 的组合测试，确认卡片失败文本保留标题和客户信息。既有 Notification 文本 label/URL 断言保持。

无依赖、数据库或去重变更；无新取消、队列或第二套生产 transport。回滚本项原子改动即可。
