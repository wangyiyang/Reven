# Research: 近期 Agent、飞书对话与主动提醒的 module 深化机会

- Query: 沿近期热点的真实调用链，找到能集中知识、提升测试 locality 与调用方 leverage 的 module 深化机会；不设计具体 interface、不重构代码。
- Scope: internal；重点为 `server/src/reven/agent/`、`integrations/feishu_bot/`、CRM MCP 工具、主动提醒及其组合根连接。
- Date: 2026-10-01

## Findings

### 结论与优先级

收敛为三个独立候选。优先建议 **CRM 客户跟进变更 module**：两个真实入口正在重复承担同一业务操作的查找、归属、校验和变更顺序，既有领域规则与数据库行为测试可以直接支撑深化。其次是飞书消息交付，再次是会话模型身份。

| 顺位 | 中文领域名称 | 推荐强度 | 确证摩擦 | 主要 leverage / 风险 |
| --- | --- | --- | --- | --- |
| 1 | CRM 客户跟进变更 module | Strong | REST 与 MCP 都在 CRM module 外查 ORM、检查不存在、保证归属后才执行变更；MCP 直接依赖网页请求校验模型 | 两个现有入口获得完整业务操作，规则 locality 提升；风险主要是错误映射、部分更新与事务语义 |
| 2 | 飞书消息交付 module | Strong | 通知与引用回复分别通过 httpx / lark SDK 实现卡片降级；纯文本保留标题的知识仍分散在调用方 | 同一交付策略覆盖通知和回复；风险主要是同步 SDK 回调与异步主循环的接线 |
| 3 | 会话模型身份 module | Worth exploring | 飞书 dispatcher 掌握会话 override 与现读注册表，runtime 掌握生效默认模型、harness 池及别名，AgentService 仅转发 | 同一 seam 验证模型选择与实际运行的组合行为；必须保留已拍板的会话与运行时取舍 |

本轮只静态阅读代码和测试，**没有运行测试，不声称测试失败或生产 bug 已复现**。以下“未覆盖”指已阅读测试集合中没有对应行为断言，并非断言所有历史或外部测试都不存在。

### 已读取的约束与排除项

- `.trellis/workflow.md`：研究结果必须落盘，规划阶段不修改产品代码。
- `.trellis/spec/reven-server/backend/index.md`：本轮关联 Agent、飞书通知和 CRM 契约。
- `.trellis/spec/reven-server/backend/agent-dsh-contract.md:7-22`：嵌入式 dsh、MCP loopback、禁止全局锁、启动失败降级、无 resume、进程内别名重铸。
- `.trellis/spec/reven-server/backend/agent-dsh-contract.md:30`：配置变更需要重启生效。
- `.trellis/spec/reven-server/backend/feishu-app-notification-contract.md:22-31`：卡片失败降级并保留内容；白名单预检先于外显回复；SDK 处理器立即返回；120 秒超时不取消 dsh；RSS 去重保持既有 run 字段。
- `.trellis/spec/reven-server/backend/crm-contract.md:36-79`：上海日期、空串归一、客户归属、主联系人、历史快照与当前计划的事务语义。
- `docs/agent-architecture.md:35-58,106-111`：Agent 原初薄封装为隔离上游，飞书负责确定性指令和 IM 会话映射。
- `.trellis/tasks/archive/2026-09/09-22-architecture-deepening/design.md`：集成凭证 + ProviderClients、Settings 组合根、连接测试注册表、Web CRUD 与路由深化已经完成，本轮不重复建议。
- 父会话已经确认仓库没有 `GLOSSARY.md`、`docs/adr/`。领域名称按 CRM 现有的客户、联系人、跟进记录、当前跟进计划，以及飞书会话、模型、通知使用，不创造“人才线索”聚合。

### 候选 1：CRM 客户跟进变更 module

#### Files found

| 文件与位置 | 作用 |
| --- | --- |
| `server/src/reven/crm/service.py:20-100` | 事务变更及部分领域不变量；目前公开 session / repository，变更常接收调用方先查到的 ORM 对象 |
| `server/src/reven/crm/repository.py:82-137` | 持久化与客户范围的联系人、跟进查找 |
| `server/src/reven/api/routes/crm.py:35-39,67-88,105-138,155-197` | REST 入口，自行取实体、检查不存在、映射 CRM 错误 |
| `server/src/reven/agent/tools_crm.py:21-31,188-204,260-314,403-429` | MCP 入口，重复上述业务操作接线并输出中文文本 |
| `server/src/reven/api/schemas/crm.py:36-74,142-178` | 两个入口复用的请求校验；目前放在网页传输目录 |
| `server/tests/api/test_crm.py:130-199` | REST 行为、归属、历史与当前计划、快照保留 |
| `server/tests/agent/test_tools_crm.py:24-34,54-84,144-175,184-255,338-378` | PostgreSQL 驱动 MCP 工具行为及真实 MCP 调用 |

#### 确证摩擦与调用链

以“修改客户的一条跟进记录”为例：

```text
REST 入口
  → CrmRepository 查 customer_id + follow_up_id
  → 判断不存在并返回 404
  → CrmService 修改已查到的 ORM 对象
  → 将联系人归属/行动日期配对错误转换为 HTTP 结果

MCP 入口
  → 从 api.schemas.crm 校验输入
  → service.repository 查 customer_id + follow_up_id
  → 判断不存在并抛 ToolError
  → CrmService 修改已查到的 ORM 对象
  → 将同一组领域错误转换为模型可读结果
```

- REST 的顺序在 `api/routes/crm.py:176-184`；MCP 的顺序在 `agent/tools_crm.py:403-414`。两个调用方都必须知道应该先做有客户范围的查找，而不能只按跟进 ID 取记录。
- 主联系人唯一、当前计划同步、快照更新已有 locality：`crm/service.py:43-55,61-81` 集中这些规则，因此该 module 有真实 depth；问题是“完整变更”的前半段仍是 interface 外的使用知识。
- `crm/service.py:22-23` 公开持久化对象，两个调用方可以直接使用 repository；`update_contact`、`update_follow_up` 收 ORM，对客户归属正确与否依赖调用方完成预检。
- MCP 向 `api.schemas.crm` 导入是已发生的耦合，见 `tools_crm.py:21-28`。复用校验本身符合 DRY；需要调整的是校验规则的所有权，不是复制一份校验。
- 请求校验不是唯一领域校验：创建时行动日期配对在 `api/schemas/crm.py:53-56,155-160`，部分更新合并旧值后的配对在 `crm/service.py:30-36,72-81`。调用方要理解两处不同阶段。深化应保留这个阶段区别并集中语义，不草率合并成只检查提交字段的函数。

这不是“586 行文件必须拆分”的建议，也没有发现已证实的归属漏洞。现有两个入口现在都执行了范围查找；摩擦在维护完整业务操作时需要同步修改两个 adapter。

#### 概念方向（无具体 interface）

深化既有 CRM 业务 module，让一次客户、联系人或跟进变更的实体查找、客户范围确认、有效输入、历史/当前计划规则及提交成为其拥有的行为。REST 与 MCP adapter 保留各自传输输入差异、错误结果格式和展示文案；领域校验从网页目录归属到 CRM 概念，避免另一层重新解释同一规则。

将持久化作为该 module 的内部 seam；不要在外部 interface 继续要求调用方先查 ORM、拼出 transaction 顺序。也不要为了相同 CRUD 形状引入跨 CRM/财务/项目的通用 module。

#### Locality、leverage 与 deletion test

- **locality**：客户范围和缺失行为与变更在同一处；修改跟进规则时不需要在 MCP 与 REST 内各重建正确调用顺序。
- **leverage**：两个已存在的生产 adapter 都能表达完整领域意图，测试只需理解一次业务操作，而不需要把 repository 与 mutator 拼接起来。
- **deletion test（现状）**：删除 `CrmService`，主联系人、历史快照、当前计划和提交规则不会消失，会散落到两个入口；说明它值得保留。删除几个纯转发辅助函数则只消除导航负担，不能解决操作所有权。
- **deletion test（深化后）**：撤掉调用方的“查实体 → 判断不存在 → 传 ORM”接线，复杂度集中到已有 CRM module 的实现中；不在其上叠一个通用 facade，也不把逻辑搬到另一个命名更大的文件。

#### 真实 adapter 与依赖类别

- 生产入口已有 REST 与 MCP 两个 adapter；不是为未来渠道建立假想 seam。
- 持久化是 SQLAlchemy/PostgreSQL。工具测试直接使用 `TEST_DATABASE_URL` 的 PostgreSQL，见 `test_tools_crm.py:24-34`，不是仓库 mock。测试数据库未配置时这些测试会 skip。
- 依赖类别：in-process 领域校验与状态变更 + local-substitutable 数据库测试实例。数据库留在内部 seam，现有 ORM 不必再包一层仅用于测试的 repository protocol。
- MCP 测试另有真实内存 FastMCP Client，`test_tools_crm.py:338-378`；它只在该协议用例中验证注册工具集及 create/list/funnel，并未通过 MCP 协议覆盖每一条错误/更新行为。

#### 测试实际覆盖及深化后的验证面

- `test_tools_crm.py:54-84`：客户 create/get/update/delete、空串清空。
- `test_tools_crm.py:144-175`：联系人 CRUD 与主联系人切换。
- `test_tools_crm.py:184-217`：跟进 CRUD、创建时同步当前计划。
- `test_tools_crm.py:221-255`：联系人缺失、行动日期配对错误、跟进缺失、跨客户更新。
- `test_crm.py:130-149`：主联系人及 REST 联系人归属。
- `test_crm.py:153-185`：仅历史行动、创建同步当前计划、修改历史不覆盖当前、删除联系人保留快照。
- `test_crm.py:188-199`：跨客户删除跟进拒绝、客户级联删除。
- 已有高价值行为测试值得保留，不能因深化就删掉 adapter 的序列化/错误映射覆盖。当前没有“单一 CRM 业务 interface 被两个入口共同使用”的测试面，归属接线由两套入口测试分别证明。
- 后续若用户选择该候选，应把共享领域不变量集中在深化后同一 seam 的数据库行为测试，并让两个 adapter 的测试着重于传输差异；迁移重复领域断言应 replace-don't-layer，不能仅新增第三套完整 CRUD 测试。

#### 约束、冲突与风险

- 没有 ADR 冲突；须保持 `crm-contract.md:49-65` 的事务、不改当前计划及客户范围错误语义。
- 不改变 REST 错误码、MCP 工具名称、模型可读提示、清空字段语义；MCP 的 `clear_*` 与 REST 的显式 null 是传输差异，应留在各 adapter 的转换处。
- 不将“人才库”工具文案扩展为新领域聚合；契约明确是单所有者 B2B CRM。
- 行级并发行为不在本轮重议，不以深化为借口添加全局锁、跨聚合抽象或数据库迁移。
- 首选这一项，因为已存在的业务规则、两个入口与真数据库测试足够支持小步替换，收益比会话生命周期调整更可控。

#### Before / After 报告结构

```text
Before
REST adapter [查找·归属·缺失] ─┐
                              ├→ CRM module [部分不变量·提交] → PostgreSQL
MCP adapter [查找·归属·缺失] ──┘
        ↑ 同时依赖网页校验规则

After
REST adapter [传输·错误格式] ──┐
                              ├→ CRM 客户跟进变更 module
MCP adapter [传输·中文表达] ───┘   [查找·归属·校验·历史/当前计划·提交]
                                      → 内部持久化 seam → PostgreSQL
```

### 候选 2：飞书消息交付 module

#### Files found

| 文件与位置 | 作用 |
| --- | --- |
| `server/src/reven/integrations/feishu_bot/client.py:83-112,129-181` | 通知用 httpx adapter、卡片 → 文本降级、鉴权及脱敏错误 |
| `server/src/reven/integrations/feishu_bot/handlers.py:139-167` | 引用回复另建 lark SDK client，闭包内再次实现交付策略 |
| `server/src/reven/integrations/feishu_bot/cards.py` | 已共用的 schema 2.0 卡片构建；不是本轮要替换的浅 module |
| `server/src/reven/provider_clients.py:128-142` | RSS 通知在调用方自行构建 markdown 与保留标题的 fallback_text |
| `server/src/reven/notify/notifier.py:40-67` | 主动推送的定向会话 → 白名单通道降级 |
| `server/src/reven/notify/scheduler.py:118-123` | 主动提醒仍要求调用方传 fallback_text，当前等于正文 |
| `server/src/reven/integrations/feishu_bot/chat_dispatcher.py:123-191` | 工作线程回复与主循环桥接；迁移必须保留 |
| `server/tests/integrations/feishu_bot/test_client.py:67-109,124-165` | httpx 发送与卡片降级行为 |
| `server/tests/integrations/feishu_bot/test_handlers.py:295-365` | SDK 回复替身和独立降级测试 |
| `server/tests/notify/test_notifier.py:34-44,64-126` | ProviderClients + MockTransport 验证通道选择 |

#### 确证摩擦与调用链

```text
RSS / 主动提醒
  → 调用方组合标题、markdown、fallback_text
  → FeishuBotApiClient
  → httpx adapter

飞书引用回复
  → dispatcher 工作线程持有 reply 闭包
  → handlers 内 reply_once + card/text 决策
  → lark SDK adapter
```

- 卡片构建已共享，但“卡片失败再发文本、两者失败才报错”的策略仍有三段：`client.py:83-90`、`client.py:92-101`、`handlers.py:160-167`。
- 引用回复的 SDK 细节和交付策略藏在入站 handler 构建函数中。维护一个“出站可达”的概念必须在入站构造与异步出站 module 之间跳转。
- 两套错误路径不同：`client.py:180-181` 将 httpx 网络异常映射成 `FeishuBotApiError`，卡片路径捕获该错误并尝试文本；`handlers.py:162` 的 `reply_once` 若直接抛异常，则不会进入 `:165` 的文本尝试。这是代码级异常路径差异；没有做 SDK 真实网络故障注入，不能写成已复现生产 bug。
- 内容保留的 interface 知识泄漏：RSS 的 `provider_clients.py:132-141` 明确自行拼入标题/阶段/摘要/链接；主动提醒的 `notify/scheduler.py:118-122` 却传正文作为 fallback_text。结合 `client.py:90,101` 可以静态确认后者的标题不会自动加入文本。应把该处看作需要独立回归验证的具体行为缺口，而不是用一行修标题代替架构候选。
- `.trellis/spec/reven-server/backend/feishu-app-notification-contract.md:22` 已要求出站由应用客户端负责，但引用回复仍在 handlers 内直接调用 SDK。候选与收拢出站所有权的契约方向一致。

#### 概念方向（无具体 interface）

让同一个飞书消息交付 module 拥有卡片与纯文本表示、降级决策、保留必要内容、脱敏失败以及实际投递的行为。通知与引用回复是两个真实调用方；接收人、定向会话与引用消息的传输差别留在内部 adapter，调用方无需重建卡片失败的分支。

优先深化既有飞书出站 module，删除 handlers 里的交付策略；不要同时留下两份策略再套一个“统一消息”层。两种现有 transport 证明真实变异点，不意味着必须永久维护两套生产实现。是否收敛到已有 HTTP transport 需在用户选择后判断，报告不提出具体 interface。

主动推送的“定向会话失败才改投白名单”是已有渠道业务策略，与“同目标卡片失败改文本”分属不同含义。不能把两种降级混成一个自动重试，也不能让送到其他用户成为引用回复的兜底行为。

#### Locality、leverage 与 deletion test

- **locality**：飞书发送失败与内容保留规则只在出站 module 修改；入站路由保持分类与 submit 的职责。
- **leverage**：通知、定向会话和引用回复共享同一交付能力及错误测试矩阵；不再由每个调用方理解 markdown 与文本的内容对应关系。
- **deletion test（现状）**：删 `cards.py` 会让卡片协议复制到多个位置，它有用，应保留。单删 `handlers.reply` 会把完整交付决策搬入 dispatcher/调用方，复杂度不会消失；单删 `client.send_markdown_to_chat` 则仅把同一策略搬到另一个调用点。
- **deletion test（深化后）**：删两个入口中的卡片降级分支和调用方的内容补齐接线，复杂度集中到已有出站 module；其内部保留两种必要 transport 表达，外部 interface 的使用知识减少。

#### 真实 adapter 与依赖类别

- 生产已有 httpx AsyncClient adapter（`client.py:149-179`）与 lark SDK reply adapter（`handlers.py:144-158`）。
- 测试已有 respx/httpx MockTransport adapter，以及 `_FakeMessageApi`（`test_handlers.py:303-313`）满足 SDK reply seam；不是仅一个生产实现的假想抽象。
- 依赖类别：true external 飞书交付 + in-process 内容与失败策略。seam 应留在实际第三方交付处；不为 markdown 的纯字符串处理另造 public port。
- ProviderClients 凭证读取和 HTTP 生命周期此前已经深化，本轮不重新实现凭证解析、客户端缓存或配置工厂。

#### 测试实际覆盖及深化后的验证面

- `test_client.py:67-79`：卡片 schema、header、markdown 正文。
- `test_client.py:83-99,103-109`：返回非零业务码时改文本，两次失败明确报错。
- `test_client.py:124-165`：chat_id 目标类型、卡片改文本、不可达。
- `test_handlers.py:340-365`：引用回复卡片成功、业务码失败改文本、两次失败报错。替身只按 code 返回，未注入 reply 直接抛 transport 异常。
- `test_notifier.py:64-126`：定向会话、白名单、目标缺失，依赖真实 credentials + MockTransport。
- `test_chat_dispatcher.py:131-159,177-251,292-320`：回复顺序、静默白名单、dead loop、预检/对话超时、占位失败放弃；这些调用者可观察行为要保留。
- 当前两套降级测试独立证明策略；没有同一个交付 seam 上的共同内容保留/网络异常矩阵。调用方分散的标题保留没有从 CRM 场景经 scheduler 到纯文本故障降级的行为断言。
- 深化后的策略测试应 replace-don't-layer；adapter 请求形状仍需各自有限验证，不能因合并策略就删掉引用 message_id 与 receive_id_type 的必要覆盖。

#### 约束、冲突与风险

- SDK 回调必须立即返回（`handlers.py:118-125`）；任何统一出站方案都不得在该回调中 await、阻塞网络或等待 Agent。
- 工作线程与主循环桥接仍按 `chat_dispatcher.py:123-191` 运行；异步 HTTP 若被复用，必须维护 loop 所有权和协程关闭纪律。
- 白名单预检先于全部外显回复、占位发送失败放弃本轮、120 秒超时不取消 dsh 全部保持。
- 不恢复审核卡片、Webhook、outbox，不新增 RSS 去重字段；多人部分失败不能记整次成功。
- 引用回复与主动推送渠道降级不能交换收件人或丢失消息引用。

#### Before / After 报告结构

```text
Before
通知 adapter [正文 + fallback] → HTTP 发送 [card → text]
引用回复 adapter              → SDK 发送  [card → text]
                                  ↑ 重复策略、不同错误路径

After
通知 adapter ──────┐
                   ├→ 飞书消息交付 module
引用回复 adapter ──┘   [内容完整性·卡片/文本·失败决策·脱敏]
                            → 内部真实交付 seam → transport adapter
```

### 候选 3：会话模型身份 module

#### Files found

| 文件与位置 | 作用 |
| --- | --- |
| `server/src/reven/agent/service.py:6-18` | AgentService 当前只转发 runtime.chat，未拥有业务决策 |
| `server/src/reven/integrations/feishu_bot/chat_dispatcher.py:84-102,205-254` | 会话 override、注册表现读、默认/当前展示、模型错误策略 |
| `server/src/reven/integrations/feishu_bot/commands.py:31-59,62-109` | 飞书指令语法和纯文案；确定性指令仍应属于飞书 |
| `server/src/reven/agent/runtime.py:80-87,94-98,137-175,177-192` | 生效默认模型、按模型 harness 池、每模型懒启动锁、外部会话别名重铸 |
| `server/src/reven/agent/config.py:65-86` | override 配置每次现读，转为运行时配置 |
| `server/src/reven/app.py:109-115,142-143,218-237` | startup 默认快照、resolver、飞书 AgentService 装配 |
| `server/src/reven/api/dependencies.py:17-23` | REST 每次依赖解析新建 AgentService；生命周期约束 |
| `server/tests/integrations/feishu_bot/test_model_commands.py:75-100,129-237,273-354` | 对话指令与 override，Agent 用 stub |
| `server/tests/agent/test_model_switching.py:20-57,61-187` | runtime 多模型池与严格失败，用 stub harness |
| `server/tests/agent/test_runtime.py:182-233` | 重启冲突重铸与后续别名沿用，单 harness 脚本替身 |

#### 确证摩擦与调用链

```text
/model 指令 → dispatcher
  → 现读 credentials 模型注册表
  → 更新 dispatcher 内的会话 override
  → render_* 描述“当前模型”

普通文本 → dispatcher 查 override
  → AgentService（纯转发）
  → runtime 选默认/池实例
  → runtime 查别名、必要时重铸
  → harness 执行
```

- 想确认“本会话下一轮实际上用哪个模型”，需要同时读注册表、dispatcher 与 runtime。`dispatcher.py:220-221` 将注册表的 is_default 当作当前默认提示；`runtime.py:94-98,146-150` 的生效默认来自 startup 配置快照。配置变更需要重启是既定行为，不能以本候选改成自动热更新；摩擦是“已保存默认”与“生效默认”知识分属不同所有者，提示需要正确遵循既定限制。
- `dispatcher.py:228-231` 以现读表的 default 决定“清除 override”，`runtime.py:146` 以生效 default 决定使用主 harness。这是同一模型身份在不同生命周期下的不同判断来源，而非仅文件数量多。
- 会话粒度在飞书已有清晰约定：`dispatcher.py:206-208,238-239`，群内每人隔离。override 只由主循环写入，重启丢失；别名属于 runtime，重启后首次冲突再重铸。两者不是一个需要持久化的新实体。
- `AgentService` 的 interface 目前与 runtime 行为几乎一样，`service.py:18` 无附加规则。它没有把上述模型身份与业务状态藏起来，单纯再加一层包装不会增加 depth。
- 飞书把返回 session_id 丢弃（`:241`）是契约允许的做法，不是 bug。别名重铸本身已有 locality，在本候选中应继续属于 runtime 实现，不要求 IM 调用方跟踪实际 id。

#### 概念方向（无具体 interface）

收拢“用户的会话模型选择、可用性、实际生效模型”的业务所有权，让调用方不需要同时拼接注册表与运行时的不同默认判断。可以深化已有 Agent 业务入口，但具体落点与生命周期必须在用户选择后决定；不是把一个字典机械搬进现有临时对象。

飞书继续拥有 `/model` 语法、确定性指令分流、中文渲染和 chat/open_id 的 IM 会话映射；runtime 继续拥有 dsh 子进程、模型池、别名重铸及 SDK 异步包装。这样遵守 `docs/agent-architecture.md:106-111` 的既定分工，仅补齐模型选择语义的 locality，不把飞书指令实现塞入通用 Agent 入口。

#### Locality、leverage 与 deletion test

- **locality**：一处定义会话的选择与生效模型，让默认、override、拒绝/不可用和展示结果遵循同一业务结论。
- **leverage**：调用方无需分别理解现读注册表与 startup runtime 快照；同一 seam 上可以验证选择之后真正落到哪个 harness，并组合验证别名重铸。
- **deletion test（AgentService 现状）**：删除当前纯转发 AgentService，对话算法和状态复杂度不会散落，因为已经全在 runtime/dispatcher；只是少一个跳转。这能证明它目前 shallow，**不能单凭这一点证明必须增加抽象或移动全部会话逻辑**。
- **deletion test（其余现状）**：删除 dispatcher 的会话模型判断，会把选择和错误知识搬到飞书调用方；删除 runtime 的别名/池会把 SDK 复杂度散给所有调用方，它已经是有 depth 的 module，应保留。
- **deletion test（深化方向）**：以现有业务入口集中模型身份知识，移除 dispatcher 与 runtime 使用者之间的重复解释；保持 runtime 内部机制，不叠新的空 facade。若用户认为当前渠道专有语义不值得迁移，最小动作可只是移除纯转发，不强行建立新 seam。

#### 真实 adapter 与依赖类别

- Agent 业务入口已有飞书调用方和 REST 调试入口（`api/routes/agent.py:13-21`）。REST 目前没有 `/model` 或多模型输入，不能把“未来 Web 模型选择”作为必要性论据。
- 模型注册依赖已有 IntegrationCredentials 与 `_StubCredentials`（`test_model_commands.py:75-85`）；Agent 执行依赖已有 runtime 与 `_StubAgentService`（`:88-100`）；底层 harness 有生产 SDK 与 `_StubHarness`（`test_model_switching.py:20-47`）。
- 依赖类别：in-process 会话模型状态 + local-substitutable 配置数据库 + true external dsh/LLM 执行。真实变异已有 adapter，不需要新增 provider 注册抽象；核心模型身份逻辑与外部执行放在不同内部 seam。

#### 测试实际覆盖及深化后的验证面

- `test_model_commands.py:147-164`：切模型后 Agent 调用参数带 override，回复有模型落款。
- `test_model_commands.py:185-220`：切回默认清 override、当前模型展示。
- `test_model_commands.py:273-287`：会话隔离；`:289-339` 严格 override 错误与默认兜底。
- 上述测试 Agent 只记录参数或脚本化抛错（`:88-100`），不经过真实 runtime。
- `test_model_switching.py:61-98`：按 ref 使用池、缓存、未注册不回落；`:114-128` 默认 override 绕过 resolver；`:132-173` 拉起失败及 close。
- 此类测试使用独立 stub harness，默认/额外模型分别在测试 tmp 子目录（`:52-54,66`），未覆盖生产共用 dsh_home 的真实存储行为；这不是已确认的运行时问题，不能据此臆测模型切换一定丢历史。
- `test_runtime.py:182-233`：冲突重铸、别名沿用、再次失败。使用单 harness，没有与 dispatcher 指令/模型池组合。
- 已读测试未通过同一业务 seam 覆盖“切换 → 实际 harness 身份 → 恢复默认 → 重铸后继续”；也没有 mutable registry 的默认变更与实际 runtime 快照的组合断言。
- 深化后验证应以选择与真实生效结果为 observable outcome，仍使用既有 fake harness；不把内部字典作为新增测试面，也不删除 SDK 初始化/清理必要覆盖。

#### 约束、冲突与风险

- 只收拢所有权；**不重议 dsh 无 resume、别名重铸、禁止全局锁、启动失败降级**。
- 多模型当前严格语义来自 `runtime.py:67-70` 与 `dispatcher.py:242-251`：override 不可用绝不能静默回到默认；会话选择保留供用户显式恢复。
- 会话 override 维持主循环内存态，不持久化；缺省模型配置仍需要重启。不是新增状态数据库或热加载任务。
- `api/dependencies.py:17-23` 每次创建 AgentService，而 `app.py:142` 为飞书创建另一对象。若后续把状态归属到业务入口，必须解决共享生命周期；简单把 `_overrides` 挪进目前的临时 AgentService 会改变语义。
- 默认/额外 harness 与别名的组合需要进一步实测，当前无证据要求更改别名键、序列化同会话或全局锁。
- `docs/agent-architecture.md` 对“薄封装”是原初隔离意图，并非所有新业务永远留在飞书的约束；实际提案须保留确定性指令与 IM 映射的既定分工。因此推荐 Worth exploring，优先级低于前两项。

#### Before / After 报告结构

```text
Before
飞书 adapter [选择·现读默认·override·提示]
  → AgentService [转发]
  → runtime [生效默认·模型池·别名]
       ↑ 一个“当前会话模型”需要两处解释

After
飞书 adapter [指令语法·会话映射·渲染] ─┐
                                     ├→ 会话模型身份 module
REST adapter [调试对话] ──────────────┘   [选择·生效模型·严格错误]
                                            → runtime [模型池·别名·dsh]
```

### 其他已查看热点为何不列为候选

- `notify/scheduler.py:92-143` 已将时刻门、渲染、每日认领、失败释放、重试上限收在 `DailyPushScheduler.tick` 背后。`tests/notify/test_scheduler.py:74-249` 经真数据库与 FakeNotifier 直接驱动同一 seam，已经具有 depth；不能仅因 loop 与 RSS 有几行相似就合并成通用 scheduler。
- `crm/follow_up_reminder.py:24-41` 是有明确“到期客户提醒”领域内容的场景 module，而非空转发；`crm/repository.py:72-80` 为它提供带 limit 的到期查询。与 MCP 的到期客户展示在格式、上限和使用场景上不同，不把格式差异误判成需要通用报告 module。
- `notify/repository.py:18-33` 的 `was_notified` 包含 pending 认领；发送前认领提交（`scheduler.py:115-118`）后若进程骤停，可能留下 pending。需要恢复含义的单独 bug 分析与契约判断，当前不把它包装为第四项架构深化，也不改动认领机制或 RSS 去重约束。
- `app.py` 当前装配的是已深化的 credentials / ProviderClients / Settings，再次建议“把 app.py 拆开”没有具体领域收益，不列入报告。

### External references / versions

本轮没有外部资料检索，也未重新验证上游行为；以仓库契约、代码和测试为证据。

- 本地 design vocabulary：`/Users/wangyiyang/.agents/skills/codebase-design/SKILL.md` 与 `DEEPENING.md`；采用 module / interface / depth / seam / adapter / leverage / locality、deletion test、interface is the test surface、replace-don't-layer。
- `server/pyproject.toml:13-21` 声明范围：deepseek-harness-sdk `>=0.1.5rc1,<0.2`，FastMCP `>=4,<5`，httpx `>=0.28,<1`，lark-oapi `>=1.4,<2`，SQLAlchemy `>=2.0.41,<3`。这是项目声明范围，不是声称当前精确安装版本或上游最新版；没有修改 `uv.lock`。
- dsh 与 SDK 长连接机制的既定事实来自 `.trellis/spec/reven-server/backend/agent-dsh-contract.md`、`feishu-app-notification-contract.md` 及 `docs/agent-architecture.md`，候选不得以第三方未验证的新能力替代既定行为。

## Caveats / Not Found

- 只写入本任务 `research/`；未编辑代码、spec、规划文件，未做任何 git 操作。
- 热点与 main=`2a0fc61` 来自父会话的 history 审视；子研究没有重新读取 git 历史。
- 没有新增 GLOSSARY/ADR；用户尚未选择候选，领域命名只是报告用语。
- 本轮测试覆盖判定来自静态阅读。DB 测试依赖 `TEST_DATABASE_URL`，未执行不等于失败。
- 异常路径差异、标题保留及 pending 恢复风险应与“架构机会”区分；报告重点是可见的知识分散，不夸大为已复现故障。
- 会话模型方向需在选择后通过真实 runtime 与 fake harness 的组合验证收敛；不能未经证据更改别名键、会话历史语义或生命周期策略。
