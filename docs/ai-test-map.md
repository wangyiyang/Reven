# Reven AI 测试地图（全功能 / 全路径）

> 用途：给后续 AI 测试代理当“地图”。先做哪条路径、每步预期什么、哪些红线不能碰，都按本文执行。  
> 适用范围：Reven 当前 `main`（模块化单体：FastAPI + React + Supabase Postgres）。  
> 维护规则：新增/下线页面、API、权限或任务流时，必须同步更新本文；测试代理执行前先读本文件，再读 `docs/runbook.md`。

---

## 0. 测试执行原则

1. **先保护，再探索**：任何写操作前先确认环境；默认只在测试环境造数据。生产/开发环境只做只读巡检，除非 Boss 明确授权。
2. **凭证红线**：不创建、不重置、不猜测任何凭证；只使用用户显式提供或系统已配置的凭证。登录失败即停止并报告。
3. **数据卫生**：造数据统一前缀 `AITEST-YYYYMMDD-`，结束时删除；删除失败要留下清单。
4. **证据闭环**：每个用例记录：用例 ID、环境、时间、账号/会话、请求/页面路径、实际结果、截图或响应摘要、结论。
5. **同源写请求**：浏览器内写 API 必须带 `X-Reven-CSRF: 1`；跨域/curl 写请求预期被 CSRF/Origin 拦截。
6. **UI 与 API 双层验证**：UI 操作后必须回查 API/列表；API 操作后必须回查 UI 是否一致。
7. **开放词表容错**：凡来自外部系统的自由词表字段（Notion 多选/状态、RSS 标题摘要等），前端必须容忍「结构合法但取值陌生」的数据——只展示、不拦截；测试 fixture 必须包含「合法但陌生」的值（事故回归：#66，Notion 目标渠道新增「掘金」导致列表页整页报错）。
8. **翻页即巡检**：列表类页面巡检必须覆盖到最后一页，毒数据常藏在非首页（事故回归：#66 的异常行只在 `/articles?page=2`）。

---

## 1. 环境与健康检查

| 项 | 值/方式 | 预期 |
|---|---|---|
| Web 入口 | `http://dev.wangyiyang.cc:3001` | 200，静态资源加载成功 |
| 健康检查 | `GET /api/health` | `{"status":"ok"}` |
| 登录页 | `GET /login` | 显示 Reven 登录页 |
| 会话 Cookie | `reven_session` | `HttpOnly`；无 `Secure`；`SameSite=Lax` |
| 未授权保护 | 直接访问任意业务页/API | 页面跳 `/login?next=...`；API 返回 401 |
| 系统状态 | `GET /api/system/status` | database / notion_sync / scheduler 三段结构 |
| 出口 IP | `GET /api/system/egress-ip` | 可用时返回 `ip`；失败不得编造地址 |

### ENV-001 部署冒烟
- 步骤：打开 `/login` → 登录 → 逐个打开主导航 8 个入口。
- 预期：无白屏；无 5xx；未知路径回到 `/articles`；业务页都有标题、表单/列表或明确占位。

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
- **AUTH-003 未登录访问业务页**：`/finance`、`/projects`、`/playbooks`、`/rss` 均跳 `/login?next=...`。
- **AUTH-004 未登录调用业务 API**：`GET /api/projects` 等返回 401。
- **AUTH-005 登出**：调用 logout 后 Cookie 清除，业务页重新跳登录。
- **AUTH-006 深色模式**：切换后 `document.documentElement.classList` 含 `dark`，刷新保持。

---

## 3. 全局壳层与导航（SHELL）

### 路由
| 路径 | 页面 | 导航 label |
|---|---|---|
| `/articles` | 稿件列表 | 稿件 |
| `/articles/:articleId` | 稿件详情 | — |
| `/finance` | 财务收支 | 财务 |
| `/projects` | 项目库 | 项目 |
| `/playbooks` | SOP/话术库 | SOP/话术 |
| `/rss/candidates` | RSS 候选 | RSS 候选 |
| `/rss` | RSS 配置 | RSS 配置 |
| `/integrations` | 集成设置 | 集成设置 |
| `/system` | 系统状态占位 | 系统状态 |
| `*` | 兜底 | 跳 `/articles` |

### 用例
- **SHELL-001 导航完整**：8 个菜单项可见，点击均能到对应路由。
- **SHELL-002 激活态**：当前路由菜单项高亮；Logo 回到 `/articles`。
- **SHELL-003 内容区间距**：桌面端侧边栏与内容区有明显留白，内容不贴边（回归 #51）。
- **SHELL-004 移动端头部**：窄屏下头部为两行——首行 logo + 纯图标退出/主题按钮（44×44，无文字），次行为带文字标签的可横滑导航 tab（右缘渐隐提示可滑；切换路由后激活 tab 自动入视）；整页不横向溢出（回归 #62、#65）。
- **SHELL-005 Toast**：成功/失败操作只出现一次 toast；失败不得伪装成功。

---

## 4. 稿件（ARTICLES）

### 页面路径
- `/articles`：筛选、排序、分页、同步、渠道状态。
- `/articles/:articleId`：详情、预览、复制 Markdown、重试/取消任务。

### API
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/articles` | 列表，支持筛选/排序/分页 |
| GET | `/api/articles/{article_id}` | 详情 + 最近任务历史 |
| GET | `/api/articles/{article_id}/jobs/{job_id}` | 单任务详情 |
| POST | `/api/articles/{article_id}/preview/wechat` | 微信预览 |
| POST | `/api/articles/{article_id}/portable-markdown` | 复制用 Markdown |
| POST | `/api/articles/{article_id}/jobs/{job_id}/retry` | 重试失败/阻塞任务 |
| POST | `/api/articles/{article_id}/jobs/{job_id}/cancel` | 取消未开始任务 |
| POST | `/api/sync/notion` | 全量同步 Notion |
| POST | `/api/articles/{article_id}/sync` | 单篇同步，202 |
| GET | `/api/articles/{article_id}/sync-runs/{run_id}` | 查询同步运行 |

### 用例
- **ART-001 列表筛选 URL 持久化**：状态/渠道/页码/排序写入 query；刷新后保持；API 请求参数一致。
- **ART-002 列表渠道状态**：每行展示最新渠道状态；默认渠道语义正确；移动端汇总不丢状态。
- **ART-003 防重复同步**：同步请求 pending 时按钮禁用，不重复发请求。
- **ART-004 详情五区块**：概览、内容/封面、渠道时间线、任务历史、恢复建议均渲染。
- **ART-005 历史边界**：任务历史按时间倒序且有上限；相同时间按 id 倒序。
- **ART-006 微信预览沙箱**：返回 HTML 只在 sandbox iframe 渲染；不得直接注入 DOM。
- **ART-007 复制 Markdown**：使用当前校验快照；快照变旧后禁用复制并刷新。
- **ART-008 剪贴板失败**：无权限时不降级成明文复制，给出明确错误。
- **ART-009 重试仅失败渠道**：成功渠道不得重试；失败/阻塞渠道可重试并更新 revision。
- **ART-010 取消限制**：只允许取消未开始/等待任务；其他状态拒绝。
- **ART-011 异常脱敏**：集成/任务错误不泄露密钥；给出稳定 fallback 操作。
- **ART-012 畸形响应**：列表/详情/预览/动作返回非法 JSON 或缺字段时，显示本地错误，不报假成功。
- **ART-013 陌生渠道值容错**：`target_channels` 含发布链路外的规划渠道（如「掘金」）时，列表/详情正常渲染并原样展示，不报「响应格式无效」（回归 #66）。
- **ART-014 翻页巡检**：列表至少翻到第 2 页及末页，确认每页均正常渲染；分页器边界（首页/末页/超出页码）不报错。
- **ART-015 详情返回上下文**：从第 2 页或筛选态进入详情，「返回稿件索引」必须还原来源 URL（含 page/query/status/channel）；直达详情时回退列表首页（回归 #73，实现为 Link state 传递 + /articles 前缀校验）。
- **ART-016 状态一致性**：发布门禁标红（封面校验/发布前校验）时，「下一步怎么处理」必须列出对应问题与建议，不得显示「当前没有需要处理的错误」（回归 #72）。

---

## 5. RSS 发现（RSS）

### 页面路径
- `/rss/candidates`：候选队列、证据、忽略、确认入 Notion Inbox。
- `/rss`：RSS 源、正向关键词、反向关键词维护。

### API
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/rss/candidates` | 候选列表 |
| POST | `/api/rss/candidates/{item_id}/ignore` | 忽略候选 |
| POST | `/api/rss/candidates/{item_id}/confirm` | 确认推送 Notion Inbox |
| POST | `/api/rss/embeddings/rebuild` | 重建关键词 embedding |
| GET/POST | `/api/rss/sources` | 源列表/新增 |
| PUT/DELETE | `/api/rss/sources/{source_id}` | 编辑/禁用/删除源 |
| GET/POST | `/api/rss/keywords` | 关键词列表/新增 |
| PUT/DELETE | `/api/rss/keywords/{keyword_id}` | 编辑/重分类/禁用/删除关键词 |

### 用例
- **RSS-001 候选证据**：候选展示标题、来源、命中证据、素材内容。
- **RSS-002 忽略**：忽略后从队列移除；API 状态同步。
- **RSS-003 确认入 Inbox**：返回 Notion 目标；成功 toast；不得重复推送。
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
- `/integrations`：Notion / GitHub / 飞书等集成卡片；密钥只写不读。

### API
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/integrations` | 集成列表 |
| GET | `/api/integrations/{provider}` | 集成详情 |
| PUT | `/api/integrations/{provider}` | 创建/更新公开配置，可选替换密钥 |
| DELETE | `/api/integrations/{provider}/secret` | 删除密钥 |
| POST | `/api/integrations/{provider}/test` | 连接测试 |
| POST | `/api/integrations/notion/bootstrap-schema` | 初始化 Notion 字段 |

### 用例
- **INT-001 加载骨架**：加载中显示 skeleton，不得误判为未配置。
- **INT-002 密钥不回显**：已配置只显示 hint；输入框永远不放明文。
- **INT-003 GitHub 必填**：公开配置缺项时保存/测试禁用。
- **INT-004 空密钥保留原文**：保存时密钥留空不覆盖密文。
- **INT-005 显式替换密钥**：替换是独立动作；hint 更新；响应不含明文。
- **INT-006 删除密钥确认**：二次确认；取消焦点回删除按钮；删除后 hint 清空。
- **INT-007 跨卡片动作锁**：任一卡片动作进行中，其他卡片动作禁用；失败释放锁。
- **INT-008 连接测试**：无适配器 503；成功更新状态；失败原因脱敏；密钥损坏给领域错误。
- **INT-009 Notion bootstrap**：无集成 404；无密钥 409；配置错误 400 脱敏；重复执行幂等 no-op。
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
- `/projects`：项目台账；名称、目标、状态、部门、截止日、GitHub、Notion。

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
- **PRJ-003 链接字段**：GitHub/Notion URL 保存并在列表展示；外部链接新开页。
- **PRJ-004 截止日**：空值显示空/`—`，不显示 0 年 0 月；有值按日期展示。
- **PRJ-005 删除**：删除后列表移除；刷新不复活。
- **PRJ-006 未找到**：更新/删除不存在项目返回 404。
- **PRJ-007 空状态**：无项目时显示空态文案/引导。
- **PRJ-008 内容区布局**：与侧边栏有留白；表单栅格整齐，按钮不漂浮。

---

## 9. SOP / 话术库（PLAYBOOKS）

### 页面路径
- `/playbooks`：SOP、Checklist、话术、方法论；状态按 草稿 → 试行 → 正式。

### API
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/playbooks` | 列表，支持 `kind`、`status` 过滤 |
| POST | `/api/playbooks` | 新增 |
| GET | `/api/playbooks/{playbook_id}` | 详情 |
| PUT | `/api/playbooks/{playbook_id}` | 更新 |
| DELETE | `/api/playbooks/{playbook_id}` | 删除 |

### 用例
- **PB-001 新增**：标题必填；kind 限 `sop/checklist/script/method`；tags 逗号/中文逗号分隔。
- **PB-002 状态机展示**：草稿/试行/正式可筛选；非法状态被拒。
- **PB-003 内容保存**：Markdown 内容保存并回显；长内容列表截断不撑破布局。
- **PB-004 删除**：删除后列表移除；刷新不复活。
- **PB-005 未找到**：详情/更新/删除不存在 playbook 返回 404。
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
- **SYS-002 status**：database 可用性、notion_sync/scheduler heartbeat 结构正确。
- **SYS-003 egress-ip**：成功返回合法 IP；失败返回 `available:false,ip:null`，不得编造。

---

## 11. 任务与后台调度（JOBS）

> 主要经稿件详情/API 间接验证；后台 lease/重试逻辑由服务端测试覆盖，AI 巡检重点看“用户可见结果”。

### 用例
- **JOB-001 状态可见**：等待/处理中/成功/失败/阻塞/取消在 UI 有一致映射。
- **JOB-002 失败恢复建议**：封面缺失、微信白名单、GitHub 构建、Notion 字段分别给出对应建议。
- **JOB-005 同步链路依赖面**：内容同步依次依赖 Notion 可读 → 封面（仅发布期强校验，#68 起同步期容忍）→ **腾讯 COS 归档**（缺 `COS_BUCKET/COS_REGION/COS_SECRET_ID/COS_SECRET_KEY/COS_PUBLIC_BASE_URL` 任一即 `COS_NOT_CONFIGURED` 硬失败）。巡检到同步失败先按此链分诊；`content_sync_runs.error_code` 精确定位断点。
- **JOB-003 重试幂等**：重复点击不产生重复成功 toast；服务端 revision 只增加一次。
- **JOB-004 错误脱敏**：日志/toast/页面不出现 token、密钥、数据库连接串。

---

## 12. 安全与稳健性横切（SEC）

- **SEC-001 CSRF**：无 `X-Reven-CSRF` 的 POST/PUT/DELETE 被拒；跨 Origin 写请求被拒。
- **SEC-002 密钥边界**：任何 API 响应、页面、toast、console、日志不得出现明文密钥/token。
- **SEC-003 外部 URL**：Notion/GitHub 链接只接受预期 HTTPS host；危险协议被拒。
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

后端 `server/tests`：
- API：`test_articles.py`、`test_actions.py`、`test_portable_markdown.py`、`test_rss_candidates.py`、`test_rss_settings.py`、`test_integrations.py`、`test_integrations_notion.py`、`test_finance.py`、`test_projects.py`、`test_playbooks.py`、`test_system.py`
- 任务/调度：`jobs/test_runner.py`、`jobs/test_service.py`、`jobs/test_retry.py`、`jobs/test_tick_integration.py`、`test_scheduling.py`
- 配置/门禁：`test_config.py`、`test_ci_database_gate.py`

前端 `web/src`：
- 基础库：`lib/api.test.ts`、`lib/clipboard.test.ts`、`lib/external-url.test.ts`
- 页面：articles / article-detail / rss-candidates / rss-settings / integrations / finance / projects / playbooks

AI 测试地图优先级高于自动化测试清单：自动化没覆盖但地图列出的路径，仍要人工/代理验证。

---

## 15. 待纳入（未合并前不作为当前验收）

- CRM / 人才库：状态机、报价、成单路径（等 CRM 分支合并后补全）。
- `/system` 系统状态完整页。
- 财务二期：应收/应付台账、月度归档、分类词典。
- Playbook 二期：版本历史、Tag 组件、正文预览。
