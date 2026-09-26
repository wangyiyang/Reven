# 飞书应用机器人通知契约

## 1. 范围与触发

修改飞书配置、RSS 每日汇总通知、测试通知或部署通知时使用本契约。
用户已明确废弃 Webhook 群机器人，唯一业务 provider 为 `feishu_bot`。

## 2. 调用签名

- `PUT /api/integrations/feishu_bot`：`public_config` 包含 `whitelist_open_ids: string[]`、`enabled: boolean`；secret 包含 `app_id`、`app_secret`。
- `POST /api/integrations/feishu_bot/test -> IntegrationResponse`：显式发送测试消息。
- `reven.notifications.DeliveryNotifier.send(Notification)`：RSS 的统一通知口。
- `python3 scripts/notify_feishu_deploy.py`：Actions 部署通知，使用环境中的 `FEISHU_APP_ID`、`FEISHU_APP_SECRET`、`FEISHU_NOTIFY_OPEN_IDS`。

## 3. 行为契约

- RSS 每日汇总只读取应用配置，不依赖 Webhook。稿件发布、Notion 与 outbox 已由主线退役，不得恢复。
- `enabled` 控制应用机器人运行时通知与入站连接；显式发送测试由用户触发，可验证未启用配置。
- 白名单是主动通知接收人。Open ID 必须属于该应用；空白名单不能被当作发送成功。
- 通知使用文本保留标题、阶段、摘要、链接。每日汇总（含本次统计、待审核总数与候选工作台入口）是唯一候选相关主动通知，每位接收人每天最多一条；候选审核收敛到网页候选工作台，不存在任何审核卡片推送、补发或卡片按钮回调链路。只由飞书应用客户端负责出站 API 边界。
- 连接测试包含 token、`/open-apis/bot/v3/info` 和真正发送消息。前端检查返回的 `connection_status`，不能只凭 HTTP 200 显示成功。
- 汇总去重只复用 `rss_discovery_runs.notification_sent_at` 与调度器同日完成缓存：发送失败不标记、随 run 重入重试；不新增去重表或字段，也不表示每次 scheduler tick 都重发。
- 禁止将任一接收人发送失败记为整条成功。RSS 保留已有发送状态及重试行为，多人部分成功后整次重试仍可能重复发送。
- 迁移 0022 接在主线 0021 后，精确删除 `integrations.provider = 'feishu'` 行，不删除其他集成或通知历史；降级不伪造旧凭证。
- API 列表过滤退役行，旧 provider 全部路径 404；CMS provider、卡片和类型校验一致。
- Actions 三项配置全空时跳过，部分配置时报错；以应用身份发给用户，UUID 在同一个 run/attempt/收件人/内容重试间保持稳定。
- 凭证、token、原始错误响应不得出现在日志或错误提示中；保留错误码与可执行的固定提示。

## 4. 验证与错误矩阵

| 条件 | 结果 |
| --- | --- |
| 未配置、禁用或不能解密 | 运行时不能报告发送成功；错误保持脱敏 |
| 没有接收人 | 明确提示配置接收人，不能只验证凭证后成功 |
| 缺少发送权限 | 测试失败并显示权限错误，前端不得出现成功 toast |
| 多人发送部分失败 | 整次通知失败，RSS 不标记汇总已发送 |
| 旧 `feishu` 数据行存在 | API 列表隐藏，专用路径 404 |
| Actions 三项配置全空/部分缺失 | 全空跳过；部分缺失退出非零 |
| Actions token 或消息 API 失败 | 退出非零，不输出 Secret/token/响应原文 |

## 5. 正常、默认与错误案例

- 正常：只配置应用凭证和当前应用下的用户 Open ID，测试通知与 RSS 每日汇总均可发送。
- 默认：未配置 CI 通知 Secrets 的仓库仍可部署，通知步骤明确跳过。
- 错误：获取 tenant token 成功就显示“测试消息已发送”，会掩盖权限缺失。
- 错误：为汇总去重引入新表或新字段；去重只能复用 `notification_sent_at` 与同日完成缓存。

## 6. 必须覆盖的测试

- provider 退役全部 API 路径与列表过滤，配置迁移只影响旧行，降级不重建假数据。
- 应用鉴权、有效消息请求、多收件人、空白名单、权限错误和密钥脱敏。
- RSS 汇总失败重入重试不重复投递、同日重跑不重复发送；1/100/1,000 条待审核候选下同一接收人仅收到一条汇总，且包含准确待审核总数与候选工作台入口。
- 前端无 Webhook 入口、类型化保存、重复点击保护、失败不报成功。
- CI 脚本解析环境与接收人、真实请求形状、API/网络错误、同一操作稳定 UUID。

## 7. 错误与正确写法

```python
# 错误：仍要求旧 Webhook provider 才能完成应用通知。
integration = await repository.get_by_provider("feishu")

# 正确：唯一配置源为应用机器人，且需要校验 enabled、凭证与接收人。
integration = await repository.get_by_provider("feishu_bot")
```

```typescript
// 错误：HTTP 200 即显示已发送。
await requestIntegration(path, { method: "POST" })
return { message: "测试消息已发送" }

// 正确：业务状态失败必须显式进入错误路径。
const result = await requestIntegration(path, { method: "POST" })
if (result.connection_status !== "连接正常") throw new Error(result.last_error ?? "测试失败")
```
