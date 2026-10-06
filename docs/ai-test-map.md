# Reven AI 测试地图（全功能 / 全路径）

> 用途：给后续 AI 测试代理当“地图”。先做哪条路径、每步预期什么、哪些红线不能碰，都按本文执行。  
> 适用范围：Reven 源码中的功能契约（模块化单体：FastAPI + React + PostgreSQL）；部署版本须按 `docs/runbook.md` 核实，不把未合并改造当作生产现状。
> 维护规则：新增/下线页面、API、权限或任务流时，必须同步更新本文；测试代理执行前先读本文件，再读 `docs/runbook.md`。

---

## 0. 测试执行原则

1. **先保护，再探索**：任何写操作前先确认环境；默认只在测试环境造数据。生产/开发环境只做只读巡检，除非 Boss 明确授权。
2. **凭证红线**：不创建、不重置、不猜测任何凭证；只使用用户显式提供或系统已配置的凭证。登录失败即停止并报告。
3. **数据卫生**：造数据统一前缀 `AITEST-YYYYMMDD-`，结束时删除；删除失败要留下清单。
4. **证据闭环**：每个用例记录：用例 ID、环境、时间、账号/会话、请求/页面路径、实际结果、截图或响应摘要、结论。
5. **同源写请求**：浏览器内写 API 必须带 `X-Reven-CSRF: 1`；跨域/curl 写请求预期被 CSRF/Origin 拦截。
6. **UI 与 API 双层验证**：UI 操作后必须回查 API/列表；API 操作后必须回查 UI 是否一致。
7. **外部内容容错**：RSS 标题与摘要作为数据展示，危险协议或脚本不得执行。
8. **列表巡检**：待审核与已保存素材均验证分页、空态和加载错误。


---

## 1. 环境与健康检查

| 项 | 值/方式 | 预期 |
|---|---|---|
| Web 入口 | `https://reven.wangyiyang.cc` | 200，静态资源加载成功 |
| 健康检查 | `GET /api/health` | db/agent/checkpointer/background_runner 分别报告；db 故障 503，Agent 降级 200/degraded，无模型时 agent disabled |
| 登录页 | `GET /login` | 显示 Reven 登录页 |
| 会话 Cookie | `reven_session` | `HttpOnly`；有 `Secure`；`SameSite=Lax` |
| 未授权保护 | 直接访问任意业务页/API | 页面跳 `/login?next=...`；API 返回 401 |
| 系统状态 | `GET /api/system/status` | database / rss_discovery 两段结构 |
| 出口 IP | `GET /api/system/egress-ip` | 可用时返回 `ip`；失败不得编造地址 |

### ENV-001 部署冒烟
- 步骤：打开 `/login` → 登录 → 逐个打开主导航 8 个入口。
- 预期：无白屏；无 5xx；未知路径回到 `/rss/candidates`；业务页都有标题、表单/列表或明确占位。

---

## 2. 认证与会话（AUTH）

### 页面/路由
- `/login`：密码登录。
- 所有业务页：未登录跳登录；登录后按 `next` 回跳。
- 全局：退出登录、深色模式切换。

### API
| 方法 | 路径 | 说明 | 关键预期 |
|---|---|---|---|
| POST | `/api/auth/login` | 密码登录 | 成功 200 + 设置 `reven_session`；错误 401 `invalid_credentials`；频繁失败 429 `login_locked` |
| POST | `/api/auth/logout` | 退出 | 204，删除会话和 Cookie |
| GET | `/api/auth/me` | 会话探测 | 登录后 200 `{"authenticated":true}`；未登录 401 |

### 用例
- **AUTH-001 正确密码登录**：登录成功，回跳目标页，`/api/auth/me` 为 true。
- **AUTH-002 错误密码**：401，页面显示“密码错误”，不设置 Cookie。
- **AUTH-003 未登录访问业务页**：`/finance`、`/projects`、`/sops`、`/rss` 均跳 `/login?next=...`。
- **AUTH-004 未登录调用业务 API**：`GET /api/projects` 等返回 401。
- **AUTH-005 登出**：调用 logout 后 Cookie 清除，业务页重新跳登录。
- **AUTH-006 深色模式**：切换后 `document.documentElement.classList` 含 `dark`，刷新保持。

---

## 3. 全局壳层与导航（SHELL）

### 路由
| 路径 | 页面 | 导航 label |
|---|---|---|
| `/finance` | 财务收支 | 财务 |
| `/projects` | 项目库 | 项目 |
| `/sops` | SOP（标准作业流程） | SOP（标准作业流程） |
| `/rss/candidates` | RSS 候选 | RSS 候选 |
| `/rss` | RSS 配置 | RSS 配置 |
| `/integrations` | 集成设置 | 集成设置 |
| `/system` | 系统状态占位 | 系统状态 |
| `*` | 兜底 | 跳 `/rss/candidates` |

### 用例
- **SHELL-001 导航完整**：8 个菜单项可见，点击均能到对应路由。
- **SHELL-002 激活态**：当前路由菜单项高亮；Logo 回到 `/rss/candidates`。
- **SHELL-003 内容区间距**：桌面端侧边栏与内容区有明显留白，内容不贴边（回归 #51）。
- **SHELL-004 移动端头部**：窄屏下头部为两行——首行 logo + 纯图标退出/主题按钮（44×44，无文字），次行为带文字标签的可横滑导航 tab（右缘渐隐提示可滑；切换路由后激活 tab 自动入视）；整页不横向溢出（回归 #62、#65）。
- **SHELL-005 Toast**：成功/失败操作只出现一次 toast；失败不得伪装成功。

---

## 4. 已退役稿件功能

- /articles 和 /articles/:id 不再注册页面，访问后回到 RSS 候选。
- 稿件、同步与发布相关 API 不再注册；认证后请求返回 404。
- 后台只运行 RSS，不再同步稿件、执行发布或重试发布通知。

---

## 5. RSS 发现（RSS）

### 页面路径
- `/rss/candidates`：待审核候选、证据、忽略与采纳。
- `/rss/candidates?status=saved`：已保存素材。
- `/rss`：RSS 源、正向关键词、反向关键词维护。

### API
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/rss/candidates` | 候选列表 |
| POST | `/api/rss/candidates/{item_id}/ignore` | 忽略候选 |
| POST | `/api/rss/candidates/{item_id}/confirm` | 采纳并保存到 Reven |
| POST | `/api/rss/embeddings/rebuild` | 重建关键词 embedding |
| GET/POST | `/api/rss/sources` | 源列表/新增 |
| PUT/DELETE | `/api/rss/sources/{source_id}` | 编辑/禁用/删除源 |
| GET/POST | `/api/rss/keywords` | 关键词列表/新增 |
| PUT/DELETE | `/api/rss/keywords/{keyword_id}` | 编辑/重分类/禁用/删除关键词 |

### 用例
- **RSS-001 候选证据**：候选展示标题、来源、命中证据、素材内容。
- **RSS-002 忽略**：忽略后从队列移除；API 状态同步。
- **RSS-003 采纳素材**：返回 saved 记录及 saved_at；显示保存成功；重复采纳返回同一记录和原保存时间。
- **RSS-004 素材浏览**：切到已保存素材可查原文和摘要，不再显示采纳/忽略操作。
- **RSS-005 并发审核**：采纳与忽略竞争时只允许一个决策生效，重筛不能覆盖人工决策。
- **RSS-004 新增源**：URL 合法且唯一；重复 URL 被拒；新增后刷新列表。
- **RSS-005 编辑/禁用源**：共用表单回填；禁用不改变其他字段。
- **RSS-006 删除源确认**：必须二次确认；取消不删除；确认后列表移除。
- **RSS-007 关键词正反列表**：正向/反向分区展示；新增到选中列表。
- **RSS-008 关键词互斥**：同一 term 不得同时存在正/反；编辑不得制造重复。
- **RSS-009 非法配置**：非法 URL、空 term、错误 kind 均被拒并保留输入。
- **RSS-010 重建 embedding**：显式触发；返回重建结果；失败不脱敏泄露。
- **RSS-011 语义分降级排查**：候选「正向/反向语义 0.000」= 该批次 embedding degraded。查库：`SELECT embedding_status, count(*) FROM rss_items GROUP BY 1`；degraded 时看 `screening_error`（EmbeddingError=限流/网络，RuntimeError=未配 key）。根因常是 SiliconFlow 余额/RPM——`GET /v1/user/info` 看 balance。修复方向见 issue #77（退避重试 + 回填）。
- **RSS-012 候选分页性能**：`/api/rss/candidates` 必须分页返回（page/page_size/total）。回归基线：page=1 应在 ~2s 内返回 30 条（远端 Supabase RTT 约 430ms/语句）；若一次返回全量（>5MB）即退化。

---

## 6. 集成设置（INTEGRATIONS）

### 页面路径
- `/integrations`：飞书 / 翻译 / Embedding / Agent 等集成卡片；密钥只写不读。

### API
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/integrations` | 集成列表 |
| GET | `/api/integrations/{provider}` | 集成详情 |
| PUT | `/api/integrations/{provider}` | 创建/更新公开配置，可选替换密钥 |
| DELETE | `/api/integrations/{provider}/secret` | 删除密钥 |
| POST | `/api/integrations/{provider}/test` | 连接测试 |

### 用例
- **INT-001 加载骨架**：加载中显示 skeleton，不得误判为未配置。
- **INT-002 密钥不回显**：已配置只显示 hint；输入框永远不放明文。
- **INT-003 GitHub 必填**：公开配置缺项时保存/测试禁用。
- **INT-004 空密钥保留原文**：保存时密钥留空不覆盖密文。
- **INT-005 显式替换密钥**：替换是独立动作；hint 更新；响应不含明文。
- **INT-006 删除密钥确认**：二次确认；取消焦点回删除按钮；删除后 hint 清空。
- **INT-007 跨卡片动作锁**：任一卡片动作进行中，其他卡片动作禁用；失败释放锁。
- **INT-008 连接测试**：无适配器 503；成功更新状态；失败原因脱敏；密钥损坏给领域错误。
- **INT-010 畸形响应**：动作返回非法 JSON 不报成功。

---

## 7. 财务收支（FINANCE）

### 页面路径
- `/finance`：汇总卡片、筛选、新增、删除。

### API
| 方法 | 路径 | 说明 | 字段要点 |
|---|---|---|---|
| GET | `/api/finance/entries` | 列表 | 支持 `kind`、`status` 过滤 |
| POST | `/api/finance/entries` | 新增 | `name`、`kind`、`status`、`amount`、`occurred_on`；金额字符串，按分存储 |
| GET | `/api/finance/entries/{entry_id}` | 详情 | 不存在 404 |
| PUT | `/api/finance/entries/{entry_id}` | 更新 | 同上 |
| DELETE | `/api/finance/entries/{entry_id}` | 删除 | 204 |
| GET | `/api/finance/summary` | 汇总 | income/expense/net/receivable/payable cents |

### 用例
- **FIN-001 汇总展示**：五卡片与 entries 计算一致；空数据显示 0 或明确占位。
- **FIN-002 新增收入**：表单提交后 toast、列表刷新、汇总增加。
- **FIN-003 金额校验**：`0`、负数、非数字、超过两位小数据被拒；页面保留输入。
- **FIN-004 筛选**：kind/status 组合筛选与 API 参数一致。
- **FIN-005 删除**：删除后列表/汇总同步减少；刷新不复活。
- **FIN-006 未找到**：访问/更新不存在 entry 返回 404，UI 不崩。
- **FIN-007 货币格式**：列表与汇总统一 CNY 格式；金额列对齐。
- **FIN-008 空状态**：无记录时表格有明确空状态，而不是只有表头。

---

## 8. 项目库（PROJECTS）

### 页面路径
- `/projects`：项目台账；名称、目标、状态、部门、截止日、GitHub。

### API
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/projects` | 列表，支持 `status` 过滤 |
| POST | `/api/projects` | 新增 |
| PUT | `/api/projects/{project_id}` | 更新 |
| DELETE | `/api/projects/{project_id}` | 删除 |

### 用例
- **PRJ-001 新增**：必填名称；提交后列表刷新；toast 一次。
- **PRJ-002 状态筛选**：进行中/已暂停/已完成过滤正确。
- **PRJ-003 链接字段**：GitHub URL 保存并在列表展示；外部链接新开页。
- **PRJ-004 截止日**：空值显示空/`—`，不显示 0 年 0 月；有值按日期展示。
- **PRJ-005 删除**：删除后列表移除；刷新不复活。
- **PRJ-006 未找到**：更新/删除不存在项目返回 404。
- **PRJ-007 空状态**：无项目时显示空态文案/引导。
- **PRJ-008 内容区布局**：与侧边栏有留白；表单栅格整齐，按钮不漂浮。

---

## 9. SOP（标准作业流程）（SOPS）

### 页面路径
- `/sops`：程序、Checklist、话术、方法论；状态按 草稿 → 试行 → 正式。

### API
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/sops` | 列表，支持 `kind`、`status` 过滤 |
| POST | `/api/sops` | 新增 |
| GET | `/api/sops/{sop_id}` | 详情 |
| PUT | `/api/sops/{sop_id}` | 更新 |
| DELETE | `/api/sops/{sop_id}` | 删除 |

### 用例
- **PB-001 新增**：标题必填；kind 限 `procedure/checklist/script/method`；tags 逗号/中文逗号分隔。
- **PB-002 状态机展示**：草稿/试行/正式可筛选；非法状态被拒。
- **PB-003 内容保存**：Markdown 内容保存并回显；长内容列表截断不撑破布局。
- **PB-004 删除**：删除后列表移除；刷新不复活。
- **PB-005 未找到**：详情/更新/删除不存在 SOP 返回 404。
- **PB-006 空状态**：无数据时显示空态文案/引导。
- **PB-007 Tags 输入**：非法分隔/空 tags 不产生脏数据；helper 文案存在。

---

## 10. 系统状态（SYSTEM）

### 页面路径
- `/system`：当前为占位页，提示下一阶段接入。

### API
- `GET /api/system/status`
- `GET /api/system/egress-ip`

### 用例
- **SYS-001 占位页**：标题“系统状态”，文案“此页面将在下一阶段接入”。
- **SYS-002 status**：database 可用性、rss_discovery heartbeat 结构正确。
- **SYS-003 egress-ip**：成功返回合法 IP；失败返回 `available:false,ip:null`，不得编造。

---

## 11. RSS 后台调度

- 仅 RSS 发现循环运行，系统状态显示 rss_discovery 心跳。
- 抓取异常记录为本次运行错误，不阻断其他源。
- 同日重复运行不重复生成发现记录或发送已完成的汇总。
- 无外部集成配置时，既有候选仍可采纳并在已保存素材中读取。

---

## 12. 安全与稳健性横切（SEC）

- **SEC-001 CSRF**：无 `X-Reven-CSRF` 的 POST/PUT/DELETE 被拒；跨 Origin 写请求被拒。
- **SEC-002 密钥边界**：任何 API 响应、页面、toast、console、日志不得出现明文密钥/token。
- **SEC-003 外部 URL**：GitHub 链接只接受预期 HTTPS host；危险协议被拒。
- **SEC-004 iframe**：微信预览 sandbox；不得 `dangerouslySetInnerHTML` 直接上屏。
- **SEC-005 401 跳转**：非 auth API 401 统一跳登录；auth API 401 不循环跳转。
- **SEC-006 限流**：登录连续失败触发 429；恢复后可登录。
- **SEC-007 输入校验**：所有表单服务端再校验；前端禁用不等于安全。
- **SEC-008 安全响应头**：登录页与 API 响应均携带 HSTS / CSP / nosniff / Referrer-Policy / X-Frame-Options。注意静态页由 Caddy 直出（不经 uvicorn），两头都要查：`curl -sI <url>` 看 `server: Caddy`（无 via）vs `via: 1.1 Caddy`。
- **SEC-009 静态缓存策略**：`/assets/*` 指纹文件应 `immutable`；SPA 入口 HTML 必须 `no-cache`。发版后开新页（勿强刷，模拟真实用户）核对 `document.querySelector('script[src]')` 的 hash 是否已切换——2026-08-25 实测旧 tab 会卡在旧 bundle。

---

## 13. AI 测试代理标准执行流

1. **读地图**：确定本轮范围（冒烟 / 单模块 / 回归）。
2. **建会话**：用 agent-browser 命名 session，例如 `reven-ai-test-YYYYMMDD`。
3. **登录**：优先复用已授权会话；无凭证则停止，不猜密码。
4. **巡检顺序**：
   - 冒烟：ENV-001 → SHELL-001/003 → 各模块空态。
   - 单模块：列表 → 新增 → 筛选 → 详情/更新 → 删除 → 空态。
   - 回归：AUTH/SHELL/SEC 横切 + 变更模块 + 相邻模块。
5. **写操作纪律**：造数据带 `AITEST-` 前缀；结束删除；截图留证。
6. **报告格式**：
   - 结论：通过/失败/受阻。
   - 失败：用例 ID、复现步骤、实际 vs 预期、截图/响应、建议修复。
   - 受阻：缺什么权限/数据/环境，下一步谁处理。

---

## 14. 当前自动化测试锚点

- API：RSS candidates/settings、integrations、brand、finance、projects、sops、crm、talents、system。
- Agent：原生图/模型协议、数据库运行/配置/审批、25 写操作事务账本、37 工具 schema、REST 与飞书入口。
- 领域：RSS 发现/翻译/Embedding/采纳竞争/重筛、CRM/人才业务规则、飞书审核权限与重放。
- 安全：认证、CSRF、网络出站、Secret 脱敏与部署流程。
- 迁移：空库升级、经营表保留、退役 provider 清理与不可逆边界。
- 前端：导航、RSS 素材闭环、集成配置、品牌与其他经营模块。
## 15. 待纳入（未合并前不作为当前验收）

- CRM / 人才库：状态机、报价、成单路径（等 CRM 分支合并后补全）。
- `/system` 系统状态完整页。
- 财务二期：应收/应付台账、月度归档、分类词典。
- SOP 二期：版本历史、Tag 组件、正文预览。

## 16. 原生 Agent（AGENT，2026-10-06 迁移契约）

Agent 配置通过 API 管理，模型凭据继续使用集成设置页。飞书保持原会话映射与白名单。完整结构见 [Agent 架构](agent-architecture.md)，旧 DSH 历史保留归档，新运行时不自动导入。

| 用例 | 路径与操作 | 必须核实 |
| --- | --- | --- |
| AGENT-001 可信入口 | 已登录 `POST /api/agent/chat`，message/可选 session_id | 成功 JSON 仅 session_id/response，X-Agent-Run-ID 可查询；客户端 actor/额外字段被拒 |
| AGENT-002 配置版本 | GET/PUT `/api/agent/config`、GET `/api/agent/config/revisions/{id}` | prompt/tool_names 入库，下一新轮生效，原 run 保留 revision；未知工具/重复工具/空白 prompt 被拒 |
| AGENT-003 删除确认 | 删除隔离测试对象 → 查询 `/api/agent/runs/{id}` → POST `/api/agent/approvals/{id}/resolve` | 展示数据库目标与级联影响；decision 和原 session_id 绑定，未批准/错用户/错会话/目标漂移零删除，重复批准只提交一次 |
| AGENT-004 请求重发 | 相同 Idempotency-Key 或飞书 message_id 重发 | 原运行 ID 不变，无第二条跟进/履历；相同键不同输入或显式不同会话 409；不同键同意图可正常新增 |
| AGENT-005 提交后中断 | 在隔离自动化用例注入 COMMIT 后/checkpoint 前中断，再显式恢复 | 账本与业务同时提交，重放原 tool_call_id 返回旧结果；仅后序工具 task 恢复也保持原写序，无死锁 |
| AGENT-006 超时与重启 | 停止等待后查询原 run；重建 app 再 POST `/api/agent/runs/{id}/resume` | 不宣称未执行；历史/override/审批仍可读；安全检查点继续原输入，否则 needs_reconciliation，不能重新追加原消息 |
| AGENT-007 飞书确定性指令 | 确认/取消审批 UUID、状态/恢复运行 UUID、/model | 白名单现读，原 chat/open_id 校验，指令不经 LLM；SDK handler 立即返回，引用回复不变 |
| AGENT-008 模型与密钥 | 切默认/会话 override、删除运行引用模型、失效指定模型 | 下一轮生效，默认与附加模型均受未结束 run 保护；不静默换模型；响应/日志/checkpoint 无明文凭据 |
| AGENT-009 部署恢复 | 空库/存量迁移 0028 → checkpoint setup → 只读容器启动/重建 | 原生工具实际执行、PG 历史持久；UID/cap/资源限制不变；旧 DSH 卷保留，未删除或伪装新历史 |

自动化锚点：`server/tests/agent/test_native_*`、`test_persistence.py`、`test_tool_*`、`test_service*.py`、`server/tests/api/test_agent*.py`、`server/tests/integrations/feishu_bot/`、`server/tests/migrations/test_agent_persistence_migration.py`。`scripts/native_agent_smoke.py` 验证确定性工具与真实 PostgreSQL，`scripts/self_host_smoke.py` 验证原生 Linux AMD64 容器重建与同源 HTTPS。

HTTP 模型替身、真实 PostgreSQL、真实上游模型分别记录。缺安全模型凭据时标记真实模型未验证，不能以纯文本回复或替身冒充真实工具协议验收。
