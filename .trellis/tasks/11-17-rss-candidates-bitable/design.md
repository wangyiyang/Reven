# 技术设计：RSS 候选直写飞书多维表格

## 总体结论

Bitable 取代 `rss_items` 成为 RSS 候选的唯一权威存储。PG 只保留运维状态（sources / keywords / runs / checkpoint / 集成配置 / 资源绑定）。Web 工作台与 Dashboard 透过一个薄的应用层 Bitable 读写服务直接操作飞书，不再经过 PG。

## 架构分层

```
rss discovery run
  → 抓取（不变）
  → 内存筛选（原 screening 逻辑，输入改为 run 内抓取结果）
  → BitableCandidateWriter（去重键查重 + batch_create + client_token）
        ↑ advisory lock 串行化同一绑定表的写入
feishu_resource_bindings（PG，新表）
  → 管理 API → 飞书集成卡片 UI
web 工作台 / dashboard
  → BitableCandidateStore（search / update）
```

## 1. 飞书 OpenAPI 基座

- 在 `integrations/feishu_bot/client.py` 现有 `httpx` client（token 缓存、错误脱敏、64KB 上限）基础上，抽出/扩展为共享 OpenAPI client，供 Bitable 及未来文档/知识库 API 复用。
- `lark-oapi` 只保留在 `supervisor.py` 长连接。
- Bitable 端点（全部 tenant token，需 `bitable:app` 权限，应用须被加为目标表协作者）：
  - `GET /open-apis/bitable/v1/apps/:app_token/tables/:table_id/fields` — 字段校验
  - `POST .../records/search` — 查询（filter.conditions[field_name, operator, value]，分页，单页 ≤ 500）
  - `POST .../records/batch_create` — 写入（单批 ≤ 500，按 ~10 QPS 控制）
  - `POST .../records/batch_update` — 状态更新
  - `POST .../records/batch_delete` — 绑定测试探针用
- 已知 API 限制（设计须容忍）：无唯一约束、无事务、无条件更新、无 upsert；`client_token` 幂等窗口官方未明确；search 对新记录的可见时效无承诺；同表不支持并发写。

## 2. 资源绑定模型

新表 `feishu_resource_bindings`：

| 列 | 说明 |
|---|---|
| id | uuid |
| integration_id | FK → integrations.id（飞书集成） |
| resource_type | `bitable`（预留 `doc`、`wiki` 等） |
| purpose | `rss_candidates`（首个用途） |
| config | JSONB：`{app_token, table_id}` |
| enabled | bool |
| created_at / updated_at | 时间戳 |

约束：`purpose` 上部分唯一索引 `WHERE enabled`（同一用途同时只有一个启用绑定）。

管理 API（挂在现有飞书集成路由下）：list / create / update / enable / disable / delete / test。
- create/update 时校验 integration 为飞书类型且已启用。
- test 探针顺序：fields 校验（九个字段存在且类型匹配）→ search 只读查询 → batch_create 一条测试记录 → batch_delete 删除之。任一步失败返回具体失败阶段。外部同步表不支持删除时测试直接判失败。

## 3. Bitable 固定字段

| 字段 | 类型 | 来源 |
|---|---|---|
| 标题 | 文本 | item.title |
| 摘要 | 文本 | item.summary |
| 来源 | 文本 | source name |
| 发布时间 | 日期 | item.published_at |
| 原文链接 | 超链接 | item.url |
| 状态 | 单选 candidate/saved/ignored | 初始 candidate |
| 命中关键词 | 文本 | screening 结果 |
| 入库日期 | 日期 | 写入时间 |
| 去重键 | 文本 | 见下 |

去重键沿用现有三键优先级：URL > GUID > title 归一化 hash。

## 4. RSS 管线改造

- `discovery.py`：删除 `_save_if_new`；run 内抓取结果直接进内存集合，附带去重键。
- `screening_service.py`：输入改为 run 内列表（不再查 `first_seen_run_id = run_id AND status='pending'`）；输出分 `candidate` / `filtered`，只有 candidate 交给 writer。
- `BitableCandidateWriter`：
  1. run 内 seen-set 去重；
  2. 对剩余去重键分批 search 查重（已存在则跳过）；
  3. batch_create，每条带 `client_token = f"{run_id}:{dedupe_key}"`；
  4. 全过程在 PG advisory lock（key 由 binding id 派生）内执行，串行化同表写入。
- 失败边界：writer 抛错 → run 失败 → 不推进 source checkpoint → 不发成功汇总 → 下次 run 重试（去重键查重 + client_token 兜底）。
- 汇总通知里的候选数来自 writer 实际写入结果。

## 5. Web 工作台与 Dashboard

- `BitableCandidateStore`：search（按状态 filter + 分页）→ 候选列表；update（状态）。
- 采纳/忽略：先按 record_id 读取确认仍是 `candidate`，再 batch_update；读到状态已变化返回 409，前端 toast 提示并刷新列表。不做强制覆盖。
- Dashboard：candidate / saved 计数走 search 聚合；删除 `estimate_hits`（factory.py:157-202）及其 API/UI 入口。
- 前端仅改数据层 hook 与冲突提示，工作台交互不变。

## 6. 删除 rss_items

最后一个 Commit 执行：
- 迁移 drop table `rss_items`；
- 删除模型、`review_service.py`、rss 路由中的旧列表/审核端点、相关测试；
- 更新 `docs/data-architecture.md`、`docs/self-hosting*.md`、`.trellis/spec/reven-server/backend/rss-materials-contract.md`。

## 7. 回滚边界

- 无 PG/Bitable 双写。上线后旧数据随表删除不可恢复（用户已确认）。
- 代码级回滚 = revert PR；Bitable 中已写入数据保留，不回清。
- 绑定切换只影响未来 run，不做数据迁移。

## 涉及 spec

- `.trellis/spec/reven-server/backend/rss-materials-contract.md`（需更新）
- `.trellis/spec/reven-server/backend/feishu-app-notification-contract.md`
- `.trellis/spec/reven-server/backend/integration-provider-contract.md`
- web 侧集成卡片与候选工作台相关 spec
