# 技术设计：架构深化批次（GH #133-#137）

## 总体原则

- **深化而非堆叠**：每个交付都是"一个 deep module 取代 N 个浅 module"，不是新增抽象层
- **interface 即测试面**：新测试只打深化后 module 的 interface；浅 module 旧测试随迁移删除（replace-don't-layer）
- **seam 纪律**：本批次所有 seam 均为既有真实变异点（生产 httpx adapter + 测试 mock / 多 provider），不引入单 adapter 假想 seam
- **依赖类别**：R1/R3 为 true external（第三方 API → mock 测试）；R2 为 in-process；R4/R5 为 in-process + ports & adapters（自有后端）

## R1 · IntegrationCredentials + ProviderClients（#133）

### 边界与契约

```python
# server/src/reven/integrations/credentials.py（新 module）
@dataclass(frozen=True)
class FeishuBotCredentials: app_id: str; app_secret: str; whitelist_open_ids: list[str]; enabled: bool
@dataclass(frozen=True)
class EmbeddingCredentials: api_key: str; base_url: str | None; model: str
# … translation / tencent_cos / agent_llm 同型

class IntegrationCredentials:
    def __init__(self, session_factory, secret_box: SecretBox) -> None: ...
    async def resolve(self, provider: str) -> FeishuBotCredentials | EmbeddingCredentials | ... | None: ...
```

- **拥有**：SecretBox 构造（全仓唯一一处）、`_secret_hint` 剥离、env 兜底顺序、log-and-degrade 策略（读取/解密失败只记日志，返回 None）
- **调用方失去**：SecretBox 导入、repository 导入、hint 知识、env 顺序、provider 各自的错误类型分歧
- `agent/config.py` 的 `resolve_agent_config` 改为薄调用方，保持"integrations 表优先 / env fallback / 未配置返 None"语义不变（docs/agent-architecture.md 既定决策不动）

### ProviderClients

```python
class ProviderClients:  # lifespan 构建并持有
    def __init__(self, credentials: IntegrationCredentials) -> None: ...
    def feishu_bot(self) -> AsyncAbstractContextManager[FeishuBotClient]: ...  # 统一 timeout / trust_env=False / 错误映射
```

- 热点 client（feishu）可长驻；错误在 seam 处映射一次（`IntegrationUnavailable` / `IntegrationMisconfigured`），调用方仅在需要时做领域映射
- 迁移并删除 `ConfiguredRssDiscoveryTick`、`ConfiguredKeywordEmbeddingRefresher`、`ConfiguredFeishuNotifier`，调用点 ≤3 行

### 取舍与回滚

- 取舍：provider 种类目前只有 5 个，typed credentials 用 dataclass 手写而非抽象 registry——KISS，第 6 个 provider 出现时再评估
- 回滚：单 PR 还原即可恢复 5 个 `load_*_config`；迁移按"先建 seam、再逐个迁调用方"小 commit 推进，任何一步可停

## R2 · Settings 组合根（#135）

- `create_app(settings: Settings | None = None)`：None 时内部 `get_settings()` 解析一次（全仓唯一调用点）
- 下推路径：`app.state.settings` + FastAPI `SettingsDep`（routes）；后台 runner / factory 构造函数注入；csrf 等叶子收标量参数
- 删除 `app.py` 的 `_load_settings_or_none()`（第二个真相源）、`tests` 的 `cache_clear()` ×3 与 `_scrub_agent_env`
- 兼容性：测试经 `create_app(settings=test_settings)` 注入，不再 monkeypatch env + 清缓存
- 依赖：在 R1 之后做，SecretBox 构造已由 R1 收口，`routes/integrations.py` 的每请求 SecretBox 自然消失

## R3 · 显式 adapters dict（#134）

- `IntegrationService(session, secret_box, adapters: dict[str, ConnectionTestAdapter])`；`routes/integrations.py` 模块级构建一次字面量 dict
- 删除：`_CONNECTION_TEST_ADAPTERS` 全局、全部 `register_*_adapter()`、conftest 的 `_restore_*_adapter` autouse fixture
- 纯删除型：映射关系本就存在，只是从 import 副作用变为显式字面量；无复杂度迁移
- 注意与 9b60c9c（feishu 通知统一）后的 `service.py` 对齐再动手

## R4 · useResourceList + ResponsiveList（#136）

```ts
// web/src/lib/use-resource-list.ts
interface ResourceListConfig<TEntity, TForm> {
  key: string; path: string;
  toPayload: (form: TForm) => unknown; toForm: (entity: TEntity) => TForm;
  filters?: Record<string, string>;
}
interface ResourceList<TEntity, TForm> {
  itemsQuery: UseQueryResult<TEntity[]>; editing: TEntity | null;
  deleting: TEntity | null; form: TForm; submit: () => void; remove: (e: TEntity) => void;
  /* … cancel / startEdit / error 归一化 */
}
```

- seam 内拥有：query-key 纪律（`[key, filters]`）、乐观删除（cancelQueries → snapshot → setQueriesData → 失败 rollback）、`toast.error` 归一化（全仓 9 处拷贝归 1）、编辑/取消表单态
- `ResponsiveList<T>`：`{ columns: ColumnDef<T>[], card: (item) => { title, meta, actions } }`，seam 内拥有 `lg:hidden` / `hidden lg:block` 切分、空态、action 渲染、aria-label 对等
- 调用方只留字段渲染与 payload 映射；`ErrorPanel` 从 `rss-shared.tsx` 提升到 `components/ui`
- 测试策略：seam 行为对真 QueryClient 单测一次；页面 MSW 测试保留但删除重复的共享行为断言（replace-don't-layer）
- 迁移顺序：projects → sops（两份字符级拷贝先归一）→ talents → crm → finance，每页一个 commit

## R5 · routes.tsx + IntegrationCard（#137）

```ts
// web/src/routes.tsx
export const routes: RouteDef[] = [
  { path: "/projects", label: "项目", icon: FolderIcon, element: <ProjectsPage /> },
  { path: "/rss", label: "RSS", icon: RssIcon, children: [/* 源 / 关键词 / 候选 */] },
];
```

- `App` 消费生成 `<Routes>`；`AppShell` 消费生成导航；组开关 `useState<Record<string, boolean>>` 按 group id keyed + localStorage 持久化（终结 `rssOpen` 单例）
- IntegrationCard：5 个内部 sub-module 收拢为一个 card module；props 从 10 降为 `{ definition, controller }`，controller 按 provider keyed 来自 `useIntegrationsController`，形如 `{ state, actions: { save, replace, remove, test, bootstrap } }`；删除 `busyAction` 字符串编码

## 跨批次兼容与风险

- 语义红线：优雅降级、API 错误码、页面行为、迁移版本号一律不变
- R1 触及 `feishu_bot/config.py`——与 09-21-feishu-app-only 任务相邻，实施前对齐 main 当前形态
- 每个 PR 独立可回滚；批次内顺序为 R3 → R1 → R2（server），R4 → R5（web），两线可并行
