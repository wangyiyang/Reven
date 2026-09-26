# 最新主线适配与上线设计

## 配置与通知

保留 feishu_bot 的 App ID、加密 App Secret、whitelist_open_ids 与 enabled。白名单指定通知接收人与审核授权用户。显式测试可以验证未启用配置，但必须实际发送。

复用统一异步飞书应用 API 客户端。reven.notifications.ConfiguredFeishuNotifier 承担 RSS 通知装配，保留标题、阶段、摘要和链接；审核仍发送交互卡片。连接测试使用 bot/v3/info 并实际发送消息。

## 主线兼容

保留 #128 删除的 publishing/jobs/outbox 及其测试，不恢复新增 heartbeat 模块。Webhook 迁移编号调整为 0022，接在 0021_retire_publishing 后。RSS 保存本地素材，汇总与审核独立尝试，保留原有日缓存。

## 发布

先把变更 rebase 到最新 main，修复全层冲突并执行完整检查。推送功能分支创建 PR，检查通过后 squash 合并；以新的语义版本 Tag 触发完整 CI、镜像构建/扫描和 digest 部署。复用仓库发布脚本，不在生产构建或手工替换容器文件。

## 数据与验证

本次最新版本包含不可逆的 0021 和清理旧飞书配置的 0022。上线前备份数据库、环境主密钥和运行卷，记录旧镜像，并检查归档可读性。升级后检查迁移版本、登录/API/前端、已保存凭证与白名单、原生测试通知和 RSS 通知适配器。回退旧架构需要整体恢复兼容备份，不能仅切换镜像。
