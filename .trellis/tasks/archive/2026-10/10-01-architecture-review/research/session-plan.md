# Research: 会话模型身份 module 的最小实施设计

- Query: 将会话模型选择、可用性判断与生效模型身份集中到同一业务 module；尽量少改 AgentService、飞书 dispatcher、runtime、config 和装配，保持现有 `/model` 与运行时取舍。
- Scope: internal；只细化既有架构报告的第三项，未重复热点扫描，未修改产品代码、规划或 spec。
- Date: 2026-10-01

## Findings

### 结论

深化现有 `AgentService` 即可，不增加另一层 facade。它持有按**外部 session_id**索引的会话模型选择，负责选择合法性、当前生效默认的解释、严格失败和本轮结果的模型身份。飞书 adapter 只保留指令解析、IM 会话映射与中文渲染。runtime 继续拥有 harness 池、启动参数、线程包装和别名重铸。

先修共享生命周期，再迁移模型选择。`app.py` 在 lifespan 创建一个 `app.state.agent_service`，REST adapter 与飞书 adapter 复用它；不能把状态搬进目前每个 REST 请求创建的临时对象。

生效默认始终取 `runtime.default_model_ref`。现读注册表的 `is_default` 仅表示已保存默认；它与生效默认不同，就展示“重启后默认”，不得据此清除 override、声称恢复了新默认、或暗中更换主 harness。

此调整有明确 depth：调用方跨同一 interface 获得选择、执行及结果身份；模型知识有 locality，组合测试有 leverage。通过 deletion test，删除深化后的 module 会让默认解释、会话状态、失败规则和回答落款重新散回调用方。runtime 现有深度已经足够，不应再次包空层。

### 已读取的文件与代码证据

| 文件 | 现有职责与证据 |
| --- | --- |
| `GLOSSARY.md` | 当前已定义“会话模型选择”“生效模型”“会话模型身份”；本设计使用这些名称。初始架构研究写“缺少词汇表”，现在主会话已补建，不能继续沿用该缺失结论。 |
| `server/src/reven/agent/service.py:6-18` | 当前 AgentService 仅转发 runtime，`model` 选择来自调用方。 |
| `server/src/reven/api/dependencies.py:13-26` | 现有聊天 Protocol；依赖函数每次创建 AgentService，当前无共享状态。 |
| `server/src/reven/api/routes/agent.py:13-21` | REST 仅有聊天请求与 `(session_id, response)` 输出，错误映射 503/502。 |
| `server/src/reven/integrations/feishu_bot/chat_dispatcher.py:81-102,205-254` | dispatcher 持有 override、注册表现读、默认解释、调用失败策略和模型落款。 |
| `server/src/reven/integrations/feishu_bot/chat_dispatcher.py:118-191,200-203` | SDK 处理器立即返回；daemon 工作线程等待；主循环现读白名单；调度失败 close 协程。 |
| `server/src/reven/integrations/feishu_bot/commands.py:31-59,62-109` | `/model` 解析与中文文案，默认恢复、拒绝与模型不可用的意义。 |
| `server/src/reven/agent/runtime.py:73-98,137-175` | 生效默认来自 config 启动快照；默认不调 resolver；override 现读 resolver 后使用按 ref 缓存池；同 ref 懒启动使用局部锁。 |
| `server/src/reven/agent/runtime.py:177-192` | 外部 id → 活跃 id 别名；already exists 重铸一次，成功后记录，后续沿用；不能移入飞书。 |
| `server/src/reven/agent/config.py:40-86` | 默认配置启动时解析；override 配置每次现读 registry 并映射 AgentConfig。 |
| `server/src/reven/integrations/credentials.py:67-86,204-249,323-363` | typed registry；默认与附加模型；禁用/畸形过滤、凭证解析、DB/env 降级；其中条目有 secret，不适合直接作为 adapter 的展示结果。 |
| `server/src/reven/app.py:102-115,133-145,218-237` | runtime 装配 resolver；飞书创建另一 AgentService；先 start runtime，再 start supervisor。 |
| `server/src/reven/agent/errors.py:3-33` | AgentError 家族与 `AgentModelUnavailableError`，已有稳定错误码足够复用。 |
| `server/tests/agent/test_model_switching.py:20-57,61-187` | fake harness 记录 provider/model；runtime 的池、严格拒绝、默认分支、启动失败与关闭测试。 |
| `server/tests/agent/test_runtime.py:182-255` | 重铸、别名复用、再次失败、缺省 id 的测试；SDK 初始化、MCP patch 和降级也已有独立覆盖。 |
| `server/tests/integrations/feishu_bot/test_model_commands.py:75-100,129-355` | 指令适配测试只跨 stub Agent，目前无法证明真实 harness 身份与提示一致。 |
| `server/tests/integrations/feishu_bot/test_chat_dispatcher.py:67-95,130-243` | 原桥接、白名单、线程与错误测试，有价值，应保留。 |
| `server/tests/integrations/feishu_bot/test_app_lifespan.py:38-68` | supervisor 装配和无配置降级，可扩充同实例验证。 |
| `server/tests/api/test_agent_chat.py:65-98` | 当前测试直接替换 `app.state.agent_runtime`；共享 module 后测试注入点必须同步迁移。 |
| `server/tests/integrations/test_agent_model_registry.py`、`server/tests/agent/test_agent_config.py` | 真数据库凭证解析和配置映射；不应随业务测试迁移删除。 |

### 最小 interface 草图

建议在 `agent/service.py` 放以下两个不可变结果类型和 AgentService；预计无需新建文件，更无需新增 Protocol。名称可按最终代码微调，但字段含义与生命周期应保持。

```python
@dataclass(frozen=True, slots=True)
class SessionModelState:
    available_refs: tuple[str, ...]
    default_ref: str | None           # 当前进程默认 config 的身份
    current_ref: str | None           # 会话选择；无 override 时等于 default_ref
    is_override: bool
    pending_default_ref: str | None   # 已保存的新默认，仅需重启时有值


@dataclass(frozen=True, slots=True)
class AgentTurn:
    session_id: str                   # runtime 返回的实际活跃 id
    response: str
    model_ref: str | None             # 本轮捕获的生效模型；成功生产路径非空
    is_override: bool                # 本轮捕获的选择模式，不重新读取当前状态


class AgentService:
    def __init__(self, runtime: AgentRuntime,
                 credentials: IntegrationCredentials | None = None) -> None: ...

    async def model_state(self, session_id: str) -> SessionModelState: ...

    async def use_model(self, session_id: str,
                        model_ref: str) -> SessionModelState: ...

    async def chat(self, message: str,
                   session_id: str | None = None) -> AgentTurn: ...
```

三个操作即全部业务 interface。`model_state` 一次返回 list/current 所需事实，不增加一套飞书命令对象或动作枚举。`use_model` 对未配置/未启用的非默认模型抛现有 `AgentModelUnavailableError`，失败不改选择；调用方需要拒绝选项时再查询 `model_state`。只有拒绝分支多读一次 registry，避免为这一条展示路径另加错误 payload 类型或结果状态机。

依赖直接复用具体 `AgentRuntime`、`IntegrationCredentials`；生产实现与测试已有 fake adapter。继续保留并更新已有调用侧 Protocol 即可，不新增 registry Protocol、harness Protocol、SessionStore 或 provider 抽象。`AgentService.chat` 的内部 Python 返回类型有迁移，REST JSON 形状保持原样；不要为 tuple 兼容再加 `chat_with_model` 旁路。

业务结果只携带 ref/布尔事实，不能暴露 `AgentModelEntry.api_key`、base_url 或 AgentConfig。凭证仍只在已有 config/runtime 内部 seam 传递。

### module 内部规则

1. `_overrides: dict[str, str]` 用外部 session_id 作键；所有调用在 FastAPI 主事件循环执行。缺省 session_id 的聊天不创建 override，UUID 与活跃 id 仍由 runtime 生成。
2. `model_state` 现读 `credentials.agent_llm_models()`；没有 credentials 或读取返回 None 时视为无现读条目。查询结束后再读 override，输出 `current_ref = override or runtime.default_model_ref`，不从 registry 的 `is_default` 推导本轮默认。
3. `available_refs` 由现读条目的 ref 构成；若生效默认存在而现读注册表不再列出它，保留这个已配置的默认 ref 作为恢复选项。不要制造带假凭证的 AgentModelEntry。它由现存主 harness/config 提供，正好符合 runtime 默认绕过 resolver 的既有行为。
4. `pending_default_ref` 只在 registry 的已保存默认非空且与 runtime 默认不同的时候设置。它表明启动快照差异，不声称已热更新。无配置 runtime + 新保存注册表同样要明确重启后才会有主实例。
5. `use_model` 先获取 state，再做有效 ref 检查；目标等于生效默认时删除 override，其他可用目标则写入 override。状态变更和返回结果构造之间不 await。切换指令不拉起 harness、不调用 LLM、不写会话历史，保持现有延迟与行为。
6. `chat` 在进入 runtime 之前一次捕获 `override`、`model_ref` 和 `is_override`，然后 `await runtime.chat(..., model=override)`。结果携带捕获值；绝不在聊天完成后重新 query 当前选择，否则执行期间收到 `/model use` 会导致回答标错模型。
7. runtime 抛 `AgentModelUnavailableError` 时原样传播。其他 `AgentError`：无 override 原样传播；有 override 转成 `AgentModelUnavailableError(override, "调用失败")`，保留选择，日志只记 ref、error_type、稳定 error_code。上游异常 message 不进入文案或日志。飞书 adapter 只需在一种模型不可用错误上渲染明确提示，其余仍由桥兜底。
8. runtime 的先决条件保持：未配置默认时 `AGENT_NOT_CONFIGURED`，主实例启动失败时 `AGENT_RUNTIME_UNAVAILABLE`，不绕过它去偷偷启动额外模型。显式 override 时外层按既有飞书行为给模型不可用提示，默认路径仍给通用兜底。

### 保存默认与生效默认：必须显式处理的具体场景

设启动默认 A，附加模型 B；进程运行时把保存默认改成 B。

| 操作 | 结果 |
| --- | --- |
| 无 override 的 `/model current` | A（默认）；追加“已保存默认 B，重启后生效”的短提示，不将 B 宣称为当前模型。 |
| `/model list` | A 仍标默认；B 标“重启后默认”；有 override 时按实际会话选择标当前；没有差异时保持现有文案意义与顺序。 |
| `/model use B` | B 若在现读表可用，就成为明确 override；回复“已切换”，不能回复“已恢复默认”；下一轮实际走 B 的池实例。 |
| `/model use A` | 清除 override；回复“已恢复默认 A”；下一轮走启动时的 A 主实例。即使现读表已不含 A，恢复仍可用。 |
| B 被禁用/移除后普通聊天 | resolver 现读得到不可用，明确失败，主实例零调用；override 继续为 B，用户可显式恢复 A。 |
| 重新启动进程 | 新 runtime 的 default_ref 为 B，新的 AgentService 无 override；无需状态迁移、持久化或自动恢复。 |

这不是新增默认配置热更新。runtime/config 不需要重写，已有“启动默认快照 + 现读 override 可用性”行为保留。需在最终 spec/维护者说明准确区分：默认与已启动池实例的凭证/端点配置改动需重启；注册表增删/启用判定现读；尚未启动的额外实例按首用时配置启动。当前 `config.py:72` 写即时生效而总说明写需重启，实施中应由主会话补齐这层事实，不能借重构把缓存池偷偷变成热重建。

清单展示“可用”只承诺存在有效配置，不承诺上游可达，也不触发健康探测。既有启动失败/调用失败继续在真实使用时明确处理；`/model current` 在不可用 override 下仍展示所选择的 ref，而不是伪造成功或清除选择。

### renderer 的精确迁移：只修矛盾场景

- `render_model_list(state: SessionModelState)` 遍历 `available_refs`，不再消费含凭证的 AgentModelEntry。`ref == state.default_ref` 才加现有“（默认）”；**仅当 `state.is_override` 且 ref 命中 current_ref 时加“（当前会话）”**，保留当前默认无 override 时原先不加此标签的表现。`ref == pending_default_ref` 加“（重启后默认）”，并在末尾追加“已保存默认模型：B，重启后生效。”；无 pending 时原文案、编号与现读条目顺序保持。实际默认若已从现读表消失，可前置补入可恢复的默认 ref，属于存在快照差异的场景。
- `render_current(state: SessionModelState)` 仍以 current_ref + is_override 产生现有“当前会话模型：…（默认/会话指定）”；current_ref 为空时仍输出 NO_MODELS_TEXT；有 pending 时才追加同一重启提示。
- `render_use_rejected(ref, state)` 保留“未配置或未启用”的原前缀并列出选择项，和现状一样不标已有会话选择。可与清单共享一个小的内部行渲染函数，由两个真实调用点传是否标当前；不要清除业务 state，也不要让 renderer 调 module 或读库。
- `render_use_switched(ref)`、`render_use_reset_to_default(ref)`、`render_model_unavailable(ref)`、`render_answer_with_model(answer, ref)` 的内容均无需改。dispatcher 的 switched/reset 分支只看 use_model 返回的 is_override；回答落款只看 AgentTurn 的本轮 ref；它不接触 registry.is_default。
- 没有默认漂移、注册表撤销或执行中切换时，现有回复文本意义和默认表现全部保留；不顺手为默认回答增加落款或“当前会话”新标记。

### 调用方与装配迁移

| 文件 | 精准改动 |
| --- | --- |
| `agent/service.py` | 两个结果类型、共享 override、三个业务操作与严格错误归一；移除由外部传入 model 的旧聊天职责。 |
| `app.py:218-224` | build runtime 后创建唯一 AgentService(runtime, credentials)，写 `state.agent_service`；传给 `_build_feishu_bot_supervisor`。无库/配置降级仍创建 AgentService(runtime, None)。 |
| `app.py:133-145` | 接收已经创建的 AgentService；不再在飞书装配中自行 new。仍将 credentials 注入 dispatcher 负责白名单。 |
| `api/dependencies.py:13-26` | 已有聊天 Protocol 的返回改为 AgentTurn；依赖改为取 `state.agent_service`，缺失时显式报错；不得提供“找不到就重新构造”的 fallback。 |
| `api/routes/agent.py:13-21` | 从结果的 session_id/response 组装既有响应；不改 request schema，不加入 model 参数、模型管理路由或 JSON 元数据。503/502 与鉴权维持。 |
| `feishu_bot/chat_dispatcher.py:53-58,84-102,205-254` | 更新现有调用侧 Protocol 为三个操作；删除模型注册表查询、`_overrides` 与 `_override_key`；统一用飞书内部 `_session_id(chat_id, open_id)` 产生 `feishu:{chat_id}:{open_id}`，指令和普通聊天都传同一个外部 id。 |
| `feishu_bot/chat_dispatcher.py:210-235` | list/current 调 `model_state` 再 render；use 校验语法后调 `use_model`，按结果的 is_override 决定切换/恢复文案；拒绝捕获已有模型错误，再查询选项供 render。 |
| `feishu_bot/chat_dispatcher.py:237-254` | 聊天只调用 `agent.chat(text, external_id)`；按返回的本轮 is_override/model_ref 加落款；捕获模型不可用渲染既有严格提示，其余错误交桥处理。 |
| `feishu_bot/commands.py:62-109` | renderer 改消费去凭证的 SessionModelState/ref；`default_ref` 与 `pending_default_ref` 的标签分别渲染。解析、USAGE_TEXT、切换/恢复/不可用的意义保持。 |
| `agent/runtime.py`、`agent/config.py` | 产品行为无需改动。既有 default property、resolver、池和别名即可支撑；只允许必要的说明澄清，不能顺手改生命周期。 |
| `agent/errors.py` | 现有错误足够，原则上无需新增类型或改错误码。 |

IM 映射只在飞书 adapter 内；业务 module 不认识 chat_id/open_id/mention/message_id。内部 override 键是外部会话身份，不能改成重铸后的 runtime 活跃 id；飞书继续可以丢弃实际返回 id，runtime 仍负责沿用别名。

REST 保留既有调试聊天功能；同一共享业务 module 按传入的外部 session_id 查选择，不另增渠道状态或模型输入。正常 REST 自建 session 没有 override，仍走启动默认。跨入口传入相同外部 id 时是同一个业务会话，不能再创建第二份选择状态。

### 删除与保留清单

**对应搬移而删除**：dispatcher `_overrides` 字段及其生命周期说明、`_override_key`、直接调用 agent_llm_models 的模型业务判断、按 registry.is_default 判当前默认/清 override 的分支、聊天携带 model 的转发参数、dispatcher 捕获普通 AgentError 后再解释 override 的重复逻辑；REST 依赖函数里每次 new AgentService 的语句；飞书装配里第二次 new AgentService 的语句。旧 AgentService 纯转发的 chat 方法体由真实业务实现替换，不保留原版外加一层。

**保留有实际用途的内部 seam**：`resolve_agent_model_config` 不是空转发，它将现读 typed registry 映射成 AgentConfig，runtime 每轮调用它保证禁用/移除后的 cached override 也严格失败；`resolve_agent_config` 保留 startup/default/env 降级；runtime `_resolve_harness`、`_harness_for`、`_run_turn` 与 `_launch` 各自拥有池选择、局部锁、SDK 与别名机制；`credentials.agent_llm_models` 拥有凭证与条目过滤；命令 parser、各中文 renderer、白名单 `_is_allowed`、线程 `_bridge`、reply 安全包装与 supervisor 都保留。不能因“resolver 名称像薄包装”就强删 config 的实际映射职责，也不能将直接访问 runtime 私有池作为替代。

### 生命周期、线程与锁

- AgentService 在每次应用 lifespan 创建一次，与 runtime 同寿命；runtime 无配置或启动失败不会影响 module 建立、健康路由或其余功能。字典随进程/应用实例销毁，没有数据库、文件、TTL 或 resume。
- 所有 override 读写仍只在主事件循环。飞书 `_run` 工作线程只解析指令、桥接协程和 reply；SDK submit 立即返回、超时常量、daemon 线程和 `run_coroutine_threadsafe` 都不变。
- 无全局锁，也不新加同会话锁。`use_model` 现读结束后的写入不 await；在当前既有并发语义下，最后完成的切换生效，已开始的聊天使用捕获的选择。无需序列化一轮 120s LLM 执行才能接受另一条切换。
- runtime 既有 `_pool_locks[ref]` 只去重同模型首用，不锁整个执行。关闭仍由 lifespan 原清理链负责先 stop 飞书，再 close runtime，最后清理其余资源；AgentService 不新增 start/close 包装。
- 模拟重启的测试应创建新的 runtime 与新的 AgentService，不通过重用旧 AgentService 或手动清私有字典伪造进程重启。
- 运行中配置并发改动不承诺与指令读表原子一致。选中时可用、调用时不可用是正常情形，真实 chat 的 resolver 再验证并明确失败；不增加交易锁或 registry revision 系统。

### 测试保留与替换

**保留机制测试。** `test_runtime.py` 的初始化、patch/token、无配置/启动失败、重铸与仅重试一次；`test_model_switching.py` 的池缓存、严格拒绝、默认不调 resolver、拉起失败和 close；`test_agent_model_registry.py` 的真数据库/解密/env/禁用解析；`test_agent_config.py` 的配置映射都测试独立且仍存在的内部 seam，不因业务深化删除。

**保留飞书 adapter 测试。** `/model` 语法矩阵、指令不发占位不进入 harness、不污染历史、中文文案、白名单/私聊群聊路由、线程桥、dead loop、超时、占位失败、脱敏均有实际价值。现有 `test_chat_dispatcher.py` 的 stub chat 返回改成 AgentTurn；调用参数改成仅 message/session_id。错误矩阵继续验证默认兜底，模型不可用明确提示。

**替换会话规则的浅测试面。** 不在新的 stub AgentService 内再复制一个 override 状态机以维持 `test_model_commands.py`。切换、恢复、隔离、默认漂移、失败保留选择等规则迁移到 `server/tests/agent/test_service.py`，使用真实 AgentService + 真实 AgentRuntime + fake DeepSeekHarness，跨同一业务 interface 验证。原飞书端到端规则测试可直接改成这种装配并保留关键文案断言；避免同时保留全部旧参数转发断言和全部新业务断言，两套重复测试仅会锁死实现。

**更新共享实例与调试测试。** `test_agent_chat.py` 若替换执行器，应显式写 `app.state.agent_service = AgentService(stub_runtime)` 或使用现有依赖覆盖；不能继续只替换 runtime state 并误以为 AgentService 会自动跟随。新增装配断言：同一应用内 `get_agent_service` 多次返回同一对象，FakeSupervisor 获得的 dispatcher 也持有该对象；不同 create_app/lifespan 不共享 override。请求/响应校验、鉴权、503/502 保持。

### 同一业务 seam 的组合测试方案

以已有 `_StubHarness` 模式注入 `reven.agent.runtime.DeepSeekHarness`，真实装配 `AgentService`、`AgentRuntime` 与 mutable credentials。fake 按构造参数记录模型身份、所有 `(message, session_id)` 和 close 状态。default 与 extra 配置使用同一 `tmp_path / "dsh"`，贴近生产 config；already exists 由脚本化的 JsonRpcError 引出，不伪称 fake 证明真实共享磁盘行为。

1. 创建默认 A 与额外 B；query state 表示 A 默认。`use_model(sid, B)` 返回 override；harness 调用数仍为零，证明确定性指令未进 LLM。
2. `chat("第一问", sid)` 真正选中构造为 B 的 fake harness，回复中的模型标记与 AgentTurn.model_ref 均为 B；A 的 run 次数为零。
3. 让 B 首次收到外部 sid 抛 already exists，重试得到 `sid~r...`；断言返回活跃 id 重铸，下一轮仍用同一别名且 B 的池实例不重复构造。业务会话选择仍以原外部 sid 查询为 B。
4. `use_model(sid, A)` 返回无 override；下一轮真实落到 A 的主 harness，AgentTurn.is_override 为 false，身份为 A。A 若也遇到预设冲突，允许 runtime 按已有规则再重铸；随后沿用它。测试按脚本选择一种确定情况，不假设切模型必丢历史或应改别名键。
5. 再切 B 后继续聊天，断言仍由 B 的缓存实例执行；同时第二个外部 sid 仍用 A，证明隔离；所有成功模型身份与 state/落款一致。
6. B 已选后将 mutable registry 移除 B；下一次 chat 抛 AgentModelUnavailableError、A run 次数不增加、state 仍选择 B；显式 use A 后恢复成功。附加脚本测试 B 拉起或 run 失败同样不回落；默认 run 失败保留原 AgentRuntimeError。
7. 独立场景在启动 A 后把保存默认改为 B：无 override 的 current 仍为 A，pending_default 为 B；use B 是 override 并实际执行 B；use A 恢复主实例。覆盖 A 不再出现在 registry 的情况，避免无法恢复实际默认。
8. fake B 的 run 用事件控制暂停；在其执行期间 use A，随后释放 B。该轮结果身份仍为 B，而下一轮身份为 A。这验证必要的本轮捕获，不需要靠 sleep 猜测排序。
9. close runtime 后全部已创建实例关闭；新 runtime/AgentService 模拟重启采用新默认，无 override，并在预置磁盘冲突脚本下重新重铸。只断言公开状态、返回值与 fake adapter 的实际调用，不新增私有字典断言。

### 验收标准与验证命令

- 保存默认、会话选择、真实执行身份在上述组合场景一致；没有保存配置自动替换启动默认或回答错误落款。
- `/model` 语法、用法、指令无占位/无推理、会话粒度、白名单和错误提示意义不变；默认漂移时增加必要的重启提示。
- 严格 override 所有失败路径都不调用默认，选择保留，显式恢复可用；上游 secret 不进入新增日志/文案。
- 同 app 的 REST/飞书复用一个业务 module；REST 请求与 JSON 形状、鉴权和错误码不扩大；不同 app/重启没有共享 override。
- runtime/config 现有机制回归全部保留；不新增全局锁、同会话执行锁、持久化、resume、自动重启或配置热重建。
- 新文件与类不超过项目 500 行提醒阈值，函数按 50 行限制安排；不因 DTO 或 parser 引入无理由碎片 module。

建议第三项实施后运行（仓库根目录）：

```sh
uv run pytest server/tests/agent server/tests/integrations/feishu_bot server/tests/integrations/test_agent_model_registry.py server/tests/api/test_agent_chat.py -m 'not dsh_runtime' -W error::RuntimeWarning
uv run ruff check server/src/reven/agent server/src/reven/integrations/feishu_bot server/src/reven/app.py server/src/reven/api/dependencies.py server/src/reven/api/routes/agent.py server/tests/agent server/tests/integrations/feishu_bot server/tests/api/test_agent_chat.py
uv run mypy
```

真数据库部分应在既有可用 TEST_DATABASE_URL 下执行，不能把 skip 当已验证。真实 dsh 握手保留为既有 smoke：`uv run pytest server/tests/agent/test_runtime.py -m dsh_runtime`；只有相应环境支持才报告通过，不为本次重构引入真实 LLM 网络费用。

本项作为用户指定顺序中的第三项，等 CRM 与飞书交付改动完成后迁移并验收；它没有必须依赖前两项新 interface 的技术原因。共享文件若已有他人改动，应按最新内容精确迁移，不能覆盖整个 dispatcher/app 或还原前项交付行为。

### Related specs 与引用

- `.trellis/workflow.md`、`.agents/skills/trellis-brainstorm/SKILL.md`：当前仍 planning，子研究只产出 evidence/design 输入，主会话完成规划和审阅 gate。
- `.trellis/spec/reven-server/backend/agent-dsh-contract.md`：startup 降级、无 resume、别名重铸、并发不设全局锁、需重启配置。
- `.trellis/spec/reven-server/backend/feishu-app-notification-contract.md:15,23-28,35,48-51,69`：IM 会话粒度、白名单、线程桥、超时、脱敏与原兜底纪律；多模型明确失败是已实现规则，需在最终 spec 准确补充该特例，不能为了旧矩阵抹掉它。
- `docs/agent-architecture.md`：嵌入式 lifespan、IM 映射由飞书拥有、配置需重启、REST 调试请求约定。
- `/Users/wangyiyang/.agents/skills/codebase-design/SKILL.md`、`DEEPENING.md`：module/interface/depth/seam/adapter/leverage/locality；interface 是测试面，替换重复浅测试而非新增全套重复测试。

External references / versions：未新增外部技术选择，不需要重新调研已实测 SDK 事实；`server/pyproject.toml` 约束 `deepseek-harness-sdk>=0.1.5rc1,<0.2`，`uv.lock:526-527` 当前锁定 `0.1.5rc1`。文中 SDK 行为来自仓库契约与现代码，不来自未验证的新版本文档。

## Caveats / Not Found

- `docs/adr/` 未找到；当前 `GLOSSARY.md` 已存在并读取。没有发现必须重议的 ADR。
- 本次仅研究落盘，没有执行产品测试或 SDK 实测，验证命令是实施阶段建议，不能报告为已通过。
- fake harness 组合测试证明模型选择、调用身份、错误与别名编排，不能证明第三方 runtime 在共享 dsh_home 上如何保留真实历史；不据此更改别名键或无 resume 契约。
- 本轮无需新增用户产品问题：目标是按已有意义迁移并补齐默认身份一致性；保存默认仍需重启、选择失败保留、未配置/启动失败降级都由已定契约回答。主会话仍应把“漂移时显示重启提示、恢复到当前生效默认”列入最终规划摘要供用户审阅。
