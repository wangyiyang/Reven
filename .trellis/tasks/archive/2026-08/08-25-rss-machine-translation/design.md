# Design: 百度/阿里 RSS 机翻与腾讯支持移除

## Scope

本设计覆盖两个必须一起交付的变化：

1. 从集成配置、API、客户端和 CMS 中彻底移除腾讯翻译，并安全处理存量 `translate_tencent` 数据。
2. 将已配置的百度/阿里翻译接入 RSS 本地化链路，保留 Qwen 作为无配置或双供应商失败时的最终兼容兜底。

## Data Flow

```text
integrations 表
  -> 百度/阿里配置加载器（enabled + 完整解密凭证）
  -> priority 排序（同级：百度、阿里）
  -> RSS 故障切换本地化器
       -> 1,000 字符确定性分段
       -> 百度 1 QPS 限流 / 阿里客户端
       -> 当前供应商失败：下一家完整重试该条目
       -> 全部失败或无配置：Qwen 最终兜底
  -> 现有 discovery 持久化与 PartialLocalizationError 处理
```

筛选复核仍由现有 `RSS_MODEL_REVIEW_ENABLED` 路径独立控制，不进入上述翻译供应商链。

## Provider Contract and Tencent Removal

- 受支持的翻译 provider 收敛为 `translate_baidu`、`translate_aliyun`，并由单一后端常量/类型定义驱动 API 校验、列表过滤和运行时加载。
- 删除腾讯 schema、连接测试适配器、低层客户端、前端 provider 联合类型与配置卡，以及对应测试夹具和快照。
- provider 路由对 `translate_tencent` 使用既有未知 provider 语义返回 404，不保留隐藏兼容入口。
- 新 Alembic 迁移只删除 `integrations.provider = 'translate_tencent'` 的行。其他集成及密文不受影响；downgrade 为 no-op，因为已删除的凭证不能可靠恢复。
- `GET /api/integrations` 在仓储结果进入响应前过滤当前受支持 provider，作为迁移遗漏或未来未知记录的防御层。未知记录不应使前端整页解析失败。

## Runtime Configuration Loader

- 从现有 `IntegrationRepository` 读取配置并解密 secret，不新增环境变量。
- 只实例化 `enabled = true` 且所需凭证字段完整的百度/阿里配置；缺失或无法解密的配置跳过并记录不含 secret 的诊断信息。
- 输出使用显式、不可序列化 secret 的 typed config/binding，包含 provider、priority 和客户端。
- 排序键为 `(priority, provider_tiebreaker)`；同级顺序固定为百度、阿里，避免数据库返回顺序改变行为。
- 客户端/HTTP 资源的创建与关闭沿用当前应用生命周期；若 factory 创建独立资源，必须通过现有关闭路径释放。

## Translation Orchestration

- 定义最小 `TextTranslator` 协议，屏蔽百度与阿里低层响应差异；RSS 层只依赖 `translate(text, source='auto', target='zh')` 语义。
- 每次 `localize(entries)` 构造可用 binding 列表。某 provider 在任意片段、标题或摘要上失败后：
  - 丢弃该 provider 对当前条目产生的所有部分输出；
  - 用下一 provider 从标题开始完整重试；
  - 将失败 provider 从本次调用的后续条目中移除。
- 标题和非空摘要独立按不超过 1,000 字符切片，片段按输入顺序同步翻译并直接拼接。空摘要保持空值且不发调用。
- 完整重组后沿用现有标题 2,000、摘要 6,000 字符上限，确保持久化边界不变。
- 百度适配器前放置 1 QPS limiter。limiter 接受 monotonic clock 与 sleep callable，串行计算距离上次调用的剩余间隔，测试注入 fake clock/sleep。
- 供应商失败类型统一包装为不含 request headers、签名、原始 secret 或完整响应体的翻译错误；编排只根据成功/失败切换，不记录凭证。

## Qwen Compatibility Fallback

- 保留现有聊天本地化器，组合为机翻编排器的最终 fallback，而非每条结果的润色步骤。
- 没有可用机翻配置时直接调用 Qwen，保证部署迁移前后的兼容行为。
- 百度和阿里都失败时，仅针对尚未完成的当前及后续条目调用 Qwen；已成功机翻的条目不重复处理。
- Qwen 也失败时继续抛出携带已完成结果的 `PartialLocalizationError`，由现有 discovery 流程回退原文并标记 translation degraded。

## Failure and Security Semantics

- 单一 provider 的限流、超时、网络错误、5xx、业务错误或无效响应均视为可故障切换错误。
- 配置缺失不是 run 失败；它选择 Qwen 兼容路径。
- 日志最多包含 provider 名、条目索引/ID、错误类别，不包含正文响应、签名材料和 secret。
- 删除腾讯数据库行是唯一不可逆步骤；上线前须明确批准。回滚应用代码后若需腾讯能力，必须重新配置凭证。

## Test Strategy

- API/迁移：腾讯路由 404、列表过滤未知 provider、迁移精确删除且保留百度/阿里/其他记录、downgrade 不伪造凭证。
- 配置加载：enabled、完整 secret、解密失败、priority 与同级稳定排序、secret redaction。
- 编排：首选成功短路；标题或摘要/任一片段失败后完整重试；故障 provider 在后续条目禁用；全部失败与空配置走 Qwen；最终失败保留 partial results。
- 分段/限流：1,000 字符边界、顺序重组、空摘要、输出截断，以及 fake clock 下的百度 1 QPS。
- 前端：provider 类型、卡片与集成页面均无腾讯，百度/阿里配置和连接测试交互保持通过。

## Rollout

1. 在同一发布中先应用精确数据迁移，再启动只识别百度/阿里的新代码。
2. 无百度/阿里配置的环境继续使用 Qwen，不造成启动或每日任务中断。
3. 管理员配置并启用百度/阿里后，RSS 自动按 priority 使用机翻；无需新环境变量。
4. 通过现有 run 的 translation degraded 指标观察供应商错误与兜底比例，不记录敏感请求内容。
