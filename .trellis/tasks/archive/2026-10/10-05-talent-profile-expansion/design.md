# 技术设计：Talent 画像扩展

## 核心原则

画像即结构：能检索/展示的字段建列建表，长尾文本留 notes；与 CRM 同范式（嵌套端点、scoped 404、`exclude_unset` 更新），不发明新模式。

## 1. 数据模型（migration `0026`，`down_revision = "0025_crm_plan_derive"`）

`talents` 加列：
- `phone VARCHAR(50)` / `email VARCHAR(320)` / `wechat VARCHAR(100)`，均可空（长度对齐 CRM Contact）。
- `preferences JSONB NOT NULL DEFAULT '[]'::jsonb`（照抄 `tags` 的 0015 写法，server_default 同步）。

新表（FK `ON DELETE CASCADE`，`ENABLE ROW LEVEL SECURITY` 与 0013/0015 惯例一致）：

```sql
talent_experiences(
  id UUID PK, talent_id UUID FK CASCADE NOT NULL,
  company TEXT NOT NULL, title TEXT NOT NULL, description TEXT,
  start_on DATE NOT NULL, end_on DATE,            -- NULL = 至今
  created_at/updated_at timestamptz,
  CHECK (end_on IS NULL OR end_on >= start_on),
  INDEX (talent_id, start_on)
)
talent_educations(
  id UUID PK, talent_id UUID FK CASCADE NOT NULL,
  school TEXT NOT NULL, degree TEXT, major TEXT,
  start_on DATE NOT NULL, end_on DATE,
  created_at/updated_at timestamptz,
  CHECK (end_on IS NULL OR end_on >= start_on),
  INDEX (talent_id, start_on)
)
```

`test_merge_heads_migration.py` 的 `FINAL_REVISION` → `"0026_<slug>"`；新增 0026 迁移回归（information_schema + 违反区间 check 插入被拒 + 双向）。

## 2. 校验层

- talents 侧的输入校验落位以 research/touchpoints.md 的现状为准（对齐其既有模式，不把 CRM 的 inputs.py 机械搬过来）。规则：
  - 联系方式：trim、空串→null、email 正则与 CRM `_EMAIL_PATTERN` 同规则。
  - `preferences`：字符串数组，元素 trim、去空、去重（保序）；非数组/非字符串元素 → 422。
  - 子表必填：company/title（experience）、school（education）、start_on；`end_on >= start_on`（若两者都有）。
- 更新沿用 `model_dump(exclude_unset=True)` 区分未提交与显式 null。

## 3. REST 契约

- `TalentResponse` 增加 `phone/email/wechat/preferences`；创建/更新入参同步。
- 嵌套端点（与 contacts/follow-ups 同范式，scoped 404 不泄露跨人才存在性）：

| Method | Path | Result |
|---|---|---|
| `GET/POST` | `/talents/{talent_id}/experiences` | 列表（start_on 倒序，end_on NULL 最前）/ 新建 |
| `PUT/DELETE` | `/talents/{talent_id}/experiences/{experience_id}` | 更新 / 删除 |
| `GET/POST` | `/talents/{talent_id}/educations` | 同上 |
| `PUT/DELETE` | `/talents/{talent_id}/educations/{education_id}` | 同上 |

- 排序语义：`end_on IS NULL`（至今）最前，其余按 `start_on` 倒序、再 `created_at` 倒序。

## 4. 日期精度

存储一律 PG `date`；web 录入用月份粒度（`<input type="month">` 或 date 输入后序列化取 `YYYY-MM-01`），展示格式 `YYYY-MM`；`end_on=null` 展示「至今」。录入/序列化归属 web 层（与 CRM「浏览器拥有类型化序列化」的约定一致），API 只接受完整 `YYYY-MM-DD`。

## 5. 到期语义对齐（R7）

- `talents/repository.py`：`_earliest_due_subquery()`（`func.min`）改为「最新一条 interaction 的 `next_due_on`」相关标量子查询（`occurred_on desc, created_at desc, id desc limit 1`，与 CRM `_latest_due_subquery` 同构）；函数更名（如 `_latest_due_subquery`），`_filter_due` 四档比较逻辑不变。
- 列表排序不涉及到期日（talents 按 `updated_at desc`），无需改。
- 测试：新增「最新 interaction 无日期 → 旧日期不冒泡」「最新有日期 → 按最新分档」用例；既有 min 语义断言反转。

## 6. web 设计

- `types.ts` / `talents-api.ts`：Talent 类型与输入加新字段；新增 Experience/Education 类型与嵌套 CRUD 函数（日期序列化在此层，含 YYYY-MM → YYYY-MM-01）。
- `talent-form*`：加联系方式 3 字段 + 喜好输入（照抄 tags 的输入控件形态，research 给现状）；`organization` 保持独立字段不与履历联动。
- 详情页新增分区（参照 interactions-section 的增删改模式）：
  - 画像卡：联系方式（电话/邮箱/微信）、喜好标签组（preferences）。
  - `experiences-section.tsx` / `educations-section.tsx`：时间线列表（至今在前、倒序、YYYY-MM 展示）+ 行内新增/编辑/删除。
- 空态：无画像/无履历时给一句话引导，不新增路由。

## 7. 兼容与回滚

- 纯增量（加列加表），无破坏性；唯一行为变更是 R7 到期语义（issue #201 已锁定）。
- 回滚 = revert + downgrade 0026（drop 两表 + drop 四列）。

## 8. 风险与对策

- preferences 与 tags 语义混淆：字段命名+表单分组明示（能力/行业 vs 喜好/个人），spec 写清。
- 月份精度「假精度」：只允许 web 序列化层补 01，API/DB 不做二次猜测；spec 记录该约定。
- 子表端点数量翻倍带来测试量：复用 contacts/follow-ups 的测试模板，参数化覆盖。
