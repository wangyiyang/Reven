# Reven AI 测试地图（全功能 / 全路径）

> 用途：给后续 AI 测试代理当“地图”。先做哪条路径、每步预期什么、哪些红线不能碰，都按本文执行。  
> 适用范围：Reven 当前 `main`（模块化单体：FastAPI + React SPA + PostgreSQL 17 + DSH Agent）。  
> 维护规则：新增/下线页面、API、权限或任务流时，必须同步更新本文；测试代理执行前先读本文件，再读 `docs/runbook.md`。

---

## 0. 测试执行原则

1. **先保护，再探索**：任何写操作前先确认环境；默认只在测试环境造数据。生产/开发环境只做只读巡检，除非明确授权。
2. **凭证红线**：不创建、不重置、不猜测任何凭证；只使用显式提供或系统已配置的凭证。登录失败即停止并报告。
3. **数据卫生**：造数据统一前缀 `AITEST-YYYYMMDD-`（或 `AITEST-`），测试结束时必须 100% 删除清理；清理后查验数据库行数，确保零数据污染。
4. **证据闭环**：每个用例记录：用例 ID、环境、时间、账号/会话、请求/页面路径、实际结果、截图或响应摘要、结论。
5. **同源写请求**：浏览器内写 API 必须带 `X-Reven-CSRF: 1`；跨域/curl 写请求预期被 CSRF/Origin 拦截。
6. **UI 与 API 双层验证**：UI 操作后必须回查 API/列表；API 操作后必须回查 UI 是否一致。
7. **外部内容容错**：RSS 标题与摘要作为数据展示，危险协议或脚本不得执行。
8. **列表巡检**：待审核与已保存素材均验证分页、空态和加载错误。

---

## 1. 环境与健康检查

| 项 | 值/方式 | 预期 |
|---|---|---|
| Web 入口 | `https://reven.wangyiyang.cc` | 200，静态资源加载成功，Caddy 管理 Let's Encrypt 证书 |
| 健康检查 | `GET /api/health` | `{"service":"reven","status":"ok","checks":{"db":{"status":"ok"},...}}` |
| 登录页 | `GET /login` | 显示 Reven 密码登录页 |
| 会话 Cookie | `reven_session` | `HttpOnly`；有 `Secure`；`SameSite=Lax` |
| 未授权保护 | 直接访问任意业务页/API | 页面跳 `/login?next=...`；API 返回 401 |
| 系统状态 | `GET /api/system/status` | database / rss_discovery 监控结构 |
| 出口 IP | `GET /api/system/egress-ip` | 可用时返回 `ip`；失败不得编造地址 |

### ENV-001 部署冒烟
- 步骤：打开 `/login` → 登录 → 逐个打开主导航 10 个顶层入口。
- 预期：无白屏；无 5xx；未知路径回到 `/`；业务页均具备完整标题、表单/列表或明确空态占位。

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
- **AUTH-003 未登录访问业务页**：`/crm`、`/talents`、`/finance`、`/projects`、`/sops`、`/rss` 均跳 `/login?next=...`。
- **AUTH-004 未登录调用业务 API**：`GET /api/crm/customers` 等返回 401。
- **AUTH-005 登出**：调用 logout 后 Cookie 清除，业务页重新跳登录。
- **AUTH-006 深色模式**：切换后 `document.documentElement.classList` 含 `dark`，刷新保持。

---

## 3. 全局壳层与导航（SHELL）

### 路由注册表（`web/src/routes.tsx`）
| 路径 | 页面 | 导航 Label | 类型 |
|---|---|---|---|
| `/login` | 登录页 | — | 独立页面（bare） |
| `/` | 个人经营工作台 | 工作台 | 顶层导航 |
| `/crm` | 客户关系管理 | CRM | 顶层导航 |
| `/crm/customers/:customerId` | 客户详情 | — | 业务详情页 |
| `/talents` | 人才库管理 | 人才库 | 顶层导航 |
| `/talents/:talentId` | 人才详情 | — | 业务详情页 |
| `/finance` | 财务布局容器 | 财务 | 顶层导航（重定向至 `/finance/overview`） |
| `/finance/overview` | 财务概览 | — | 财务子页面 |
| `/finance/ledger` | 收支流水台账 | — | 财务子页面 |
| `/finance/pending` | 待收待付跟进 | — | 财务子页面 |
| `/projects` | 项目库台账 | 项目 | 顶层导航 |
| `/sops` | SOP 标准作业流程 | SOP（标准作业流程） | 顶层导航 |
| `/rss` | RSS 发现容器 | RSS | 顶层折叠菜单（重定向至 `/rss/sources`） |
| `/rss/candidates` | RSS 内容发现 | 内容发现 | RSS 子菜单 |
| `/rss/sources` | RSS 源维护 | RSS 源 | RSS 子菜单 |
| `/rss/keywords` | 正/反关键词维护 | RSS 关键词 | RSS 子菜单 |
| `/brand` | 品牌管理（档案/素材/模板） | 品牌管理 | 顶层导航 |
| `/integrations` | 第三方集成设置 | 集成设置 | 顶层导航 |
| `/system` | 系统服务健康状态 | 系统状态 | 顶层导航 |
| `*` | 兜底未匹配路由 | — | 重定向至 `/` |

### 用例
- **SHELL-001 导航完整**：10 个顶层入口全部可见，点击能正确进入对应路由。
- **SHELL-002 激活态高亮**：当前路由对应菜单项展示激活高亮背景；Logo 始终可回跳首页。
- **SHELL-003 内容区间距**：桌面端侧边栏与主工作区有良好间距留白，内容不贴边。
- **SHELL-004 移动端自适应**：窄屏下自适应两行头部与抽屉，不产生横向滚动溢出。
- **SHELL-005 全局 Toast**：操作成功或失败由右下角 Toast 呈现，错误不被静默吞掉。

---

## 4. 工作台与聚合监控（DASHBOARD）

### 页面路径
- `/`：工作台首页。

### API
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/dashboard/summary` | 聚合工作台经营指标与异常状态 |

### 用例
- **DASH-001 集成缺失提醒**：当系统存在未配置的外部集成时，顶部展示黄色警示横幅并列出缺失清单，提供一键直达跳转。
- **DASH-002 财务待收款聚合**：统计待收款项笔数、金额与逾期金额；点击卡片直达 `/finance/pending`。
- **DASH-003 RSS 发现概况**：统计待审核条目数、已保存素材数，展示最近定时抓取的执行状态与时间戳。
- **DASH-004 CRM 待跟进**：聚合今日到期跟进与逾期跟进客户数；点击直达 `/crm`。
- **DASH-005 进行中项目**：展示当前进行中项目数，支持快速进入项目库。

---

## 5. CRM 客户管理（CRM）

### 页面路径
- `/crm`：客户台账列表、多维筛选、新建抽屉。
- `/crm/customers/:customerId`：客户主档案、联系人子表、跟进记录与计划派生。

### API
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/crm/customers` | 客户列表，支持 `status`、`plan`、`q` 过滤 |
| POST | `/api/crm/customers` | 新增客户 |
| GET | `/api/crm/customers/{customer_id}` | 客户详情 |
| PATCH | `/api/crm/customers/{customer_id}` | 更新客户档案 |
| DELETE | `/api/crm/customers/{customer_id}` | 删除客户（级联清理联系人与跟进记录） |
| POST | `/api/crm/customers/{customer_id}/contacts` | 添加联系人 |
| PATCH/DELETE | `/api/crm/contacts/{contact_id}` | 编辑/删除联系人 |
| POST | `/api/crm/customers/{customer_id}/follow-ups` | 添加跟进记录（派生客户最新行动计划） |
| PATCH/DELETE | `/api/crm/follow-ups/{follow_up_id}` | 编辑/删除跟进记录 |

### 用例
- **CRM-001 列表展示与空态**：无客户时展示友好空态提示；表格呈现客户名、状态、来源、下一步、跟进日期、操作列。
- **CRM-002 新建客户抽屉**：必填客户名称，支持选择关系状态（潜在/跟进中/合作/暂停/已流失）、客户来源及备注；保存后即时刷新列表。
- **CRM-003 多维组合检索**：关系状态下拉与跟进计划（已逾期/今天/未来/无计划）下拉联动正确；搜索框按名称模糊匹配。
- **CRM-004 客户主档案**：详情页展示完整档案字段，支持随时呼出抽屉编辑基本信息。
- **CRM-005 联系人维护**：支持添加多名联系人，记录职位、电话、邮箱、微信，支持勾选「主要联系人」，列表优先展示主要联系人标识。
- **CRM-006 跟进记录与计划自动派生**：记录沟通方式（电话/面谈/微信/邮件/其他）、沟通内容、约定的下一步行动及下次跟进日期。最新跟进的行动计划自动覆盖成为客户当前主计划。
- **CRM-007 删除确认安全防护**：删除客户必须弹出二次确认对话框，告知联系人和跟进记录将被同步删除；确认后级联物理清理。
- **CRM-008 404 容错**：访问不存在的客户 ID 时返回 404，UI 提示资源不存在并不白屏崩溃。

---

## 6. 人才库管理（TALENTS）

### 页面路径
- `/talents`：人才台账列表、综合筛选、新建抽屉。
- `/talents/:talentId`：人才画像主档案、履历、毕业院校、接洽互动。

### API
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/talents` | 人才列表，支持 `status`、`due`、`tag`、`q` 过滤 |
| POST | `/api/talents` | 新建人才档案 |
| GET | `/api/talents/{talent_id}` | 人才详情 |
| PATCH | `/api/talents/{talent_id}` | 更新人才档案 |
| DELETE | `/api/talents/{talent_id}` | 删除人才档案 |
| POST | `/api/talents/{talent_id}/experiences` | 录入工作履历 |
| DELETE | `/api/talents/experiences/{exp_id}` | 删除履历 |
| POST | `/api/talents/{talent_id}/educations` | 录入院校背景 |
| DELETE | `/api/talents/educations/{edu_id}` | 删除院校背景 |
| POST | `/api/talents/{talent_id}/interactions` | 录入接洽跟进记录 |
| DELETE | `/api/talents/interactions/{interaction_id}` | 删除接洽记录 |

### 用例
- **TAL-001 列表展示与空态**：表格清晰展示姓名、机构、状态、标签、费率、评分及操作按钮。
- **TAL-002 新建人才抽屉**：必填姓名；支持状态（候选/接洽中/已合作/搁置）、机构、联系方式、多标签输入、合作喜好、能力要求、费率金额与单位（按小时/天/项目）及 1-5 星评分。
- **TAL-003 画像详情多维度沉淀**：详情页提供专属分区维护：
  - 工作履历（公司、职务、起止时间、经历描述）；
  - 毕业院校（学校、学位、专业、起止时间）；
  - 接洽记录（沟通方式、发生日期、沟通内容、下次跟进）。
- **TAL-004 筛选过滤**：支持按状态、跟进到期和标签聚合筛选。
- **TAL-005 删除确认安全防护**：删除人才前弹出 Dialog 确认；删除后级联清理履历、院校和跟进子表。

---

## 7. 财务收支与台账（FINANCE）

### 页面路径
- `/finance/overview`：经营概览五卡片、本月实收实付、待处理款项。
- `/finance/ledger`：按月收支流水台账、分类检索、单笔编辑与删除。
- `/finance/pending`：待收款项与待付款项跟进。

### API
| 方法 | 路径 | 说明 | 字段要点 |
|---|---|---|---|
| GET | `/api/finance/entries` | 财务条目列表 | 支持 `kind`、`status`、`month`、`category` 过滤 |
| POST | `/api/finance/entries` | 新增条目 | `name`、`kind`（income/expense）、`status`、`amount`、`occurred_on` |
| PATCH | `/api/finance/entries/{id}` | 更新条目 | 金额按分存储，更新后触发汇总重算 |
| DELETE | `/api/finance/entries/{id}` | 删除条目 | 204，从流水与汇总中移除 |
| GET | `/api/finance/summary` | 经营汇总 | income/expense/net/receivable/payable cents |

### 用例
- **FIN-001 三子页面导航**：概览、收支流水、待收待付 Tab 切换平滑。
- **FIN-002 4 种快捷录入入口**：页面顶部常驻「记收入」、「记支出」、「新增待收」、「新增待付」快捷按钮，打开抽屉预填对应类型与状态。
- **FIN-003 校验机制**：空名称或非有效金额（如负数、非数字）被前端与后端双层拦截，Toast 提示明确报错。
- **FIN-004 实时汇总联动**：记入一笔实收，概览卡片本月实收和收支净额立即增加对应金额；删除后自动归零。
- **FIN-005 流水按月检索**：年月选择器、类型选择器（全部/收入/支出）与搜索框协同过滤。
- **FIN-006 待收待付结算与核销**：待收待付列表支持直接流转标记为已结清，结清后归入实收实付流水。
- **FIN-007 二次删除确认**：删除财务记录弹出二次确认对话框，防止错账。

---

## 8. 项目库（PROJECTS）

### 页面路径
- `/projects`：项目台账列表、状态筛选、新建抽屉。

### API
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/projects` | 列表，支持 `status` 过滤 |
| POST | `/api/projects` | 新增项目 |
| PATCH | `/api/projects/{project_id}` | 更新项目 |
| DELETE | `/api/projects/{project_id}` | 删除项目 |

### 用例
- **PRJ-001 新增项目**：必填名称，选填目标、部门、截止日与 GitHub 仓库 URL。
- **PRJ-002 状态筛选**：支持按进行中 / 已暂停 / 已完成筛选。
- **PRJ-003 外部链接展示**：合法 GitHub 链接在列表中渲染为可点击超链接，点击新开窗口访问。
- **PRJ-004 二次删除确认**：点击行内删除，弹出对话框提示「删除后无法恢复，请确认这个项目已不再需要。」；确认后列表移除。

---

## 9. SOP（标准作业流程）（SOPS）

### 页面路径
- `/sops`：流程列表、分类筛选、状态机筛选、新建与查看抽屉。

### API
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/sops` | 列表，支持 `kind`、`status` 过滤 |
| POST | `/api/sops` | 新增 SOP |
| GET | `/api/sops/{sop_id}` | 详情 |
| PATCH | `/api/sops/{sop_id}` | 更新 SOP |
| DELETE | `/api/sops/{sop_id}` | 删除 SOP |

### 用例
- **SOP-001 新增**：标题必填；类型支持 `程序 / Checklist / 话术 / 方法论`；状态支持 `草稿 → 试行 → 正式`；标签逗号分隔解析。
- **SOP-002 查看抽屉**：点击行内「查看」滑出只读详情抽屉，展示完整 Markdown 内容排版。
- **SOP-003 一键复制**：查看抽屉内点击「复制内容」，将全文写入系统剪贴板。
- **SOP-004 二次删除确认**：删除前 Dialog 确认防误删。

---

## 10. RSS 内容发现与源/词配置（RSS）

### 页面路径
- `/rss/candidates`：待审核候选、证据、忽略与采纳。
- `/rss/sources`：已配置 RSS 抓取源。
- `/rss/keywords`：正向与反向筛选关键词维护。

### API
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/rss/candidates` | 候选列表（分页返回） |
| POST | `/api/rss/candidates/{item_id}/ignore` | 忽略候选 |
| POST | `/api/rss/candidates/{item_id}/confirm` | 采纳并保存到素材库 |
| GET/POST | `/api/rss/sources` | 源列表/新增源 |
| PUT/DELETE | `/api/rss/sources/{source_id}` | 编辑/删除源 |
| GET/POST | `/api/rss/keywords` | 关键词列表/新增 |
| PUT/DELETE | `/api/rss/keywords/{keyword_id}` | 编辑/删除关键词 |

### 用例
- **RSS-001 待审与已保存切换**：待审核队列与已保存素材平滑切换。
- **RSS-002 源维护**：源列表清晰呈现状态与最后抓取结果，支持快速新建源。
- **RSS-003 正反关键词分区**：正向关键词与反向关键词分区呈现，各区配备独立检索。

---

## 11. 品牌管理（BRAND）

### 页面路径
- `/brand`：品牌档案、品牌素材库、微信/博客渠道模板。

### API
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/brand/profile` | 品牌档案详情（草稿与已发布版本） |
| PUT | `/api/brand/profile` | 保存品牌档案草稿 |
| POST | `/api/brand/profile/publish` | 发布品牌档案新版本 |
| GET/POST | `/api/brand/assets` | 素材列表 / 上传品牌图片素材 |
| GET/PUT | `/api/brand/templates/{channel}` | 获取 / 更新渠道模板 |
| POST | `/api/brand/templates/{channel}/publish` | 发布渠道模板版本 |

### 用例
- **BRD-001 品牌档案配置**：品牌名、署名、简介、正文字体，主色配备拾色器与十六进制文本联动。
- **BRD-002 草稿与版本发布**：支持先保存草稿，确认无误后再发布不可逆新版本。
- **BRD-003 素材库管理**：支持上传 PNG/JPEG/WebP 图片素材，按用途（标志/二维码/封面等）分类归档。
- **BRD-004 微信公众号模板**：排版主色、字号调节及文末图文模块拖拽/顺序追加。
- **BRD-005 个人博客模板**：博客渠道独立模板设置与发布机制。

---

## 12. 集成设置（INTEGRATIONS）

### 页面路径
- `/integrations`：第三方凭证与连接状态维护。

### API
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/integrations` | 集成列表 |
| PUT | `/api/integrations/{provider}` | 更新配置与替换密钥 |
| POST | `/api/integrations/{provider}/test` | 连接可用性测试 |

### 用例
- **INT-001 密钥单向写入**：任何密钥（API Key/Secret）提交后绝不回显，只显示脱敏提示。
- **INT-002 Agent LLM 模型池**：支持维护默认模型与附加模型列表，打通飞书 `/model` 指令。
- **INT-003 连接测试**：提供显式测试按钮，失败信息安全脱敏呈现。

---

## 13. 系统状态（SYSTEM）

### 页面路径
- `/system`：系统组件实时运行状态监控。

### API
- `GET /api/system/status`
- `GET /api/system/egress-ip`

### 用例
- **SYS-001 服务健康状态**：实时展示后端服务（reven）、PostgreSQL 数据库连通性。
- **SYS-002 调度心跳**：呈现 RSS 发现后台循环的最近心跳时间戳。
- **SYS-003 手动刷新**：点击「刷新」按钮，即时轮询最新状态。

---

## 14. 安全与稳健性横切（SEC）

- **SEC-001 CSRF 保护**：所有浏览器写请求校验 `X-Reven-CSRF: 1`。
- **SEC-002 密钥边界**：前端所有响应和页面均不可见明文 Key。
- **SEC-003 401 自动跳转**：会话失效时平滑引导回登录页。
- **SEC-004 误删二次确认**：CRM、人才、财务、项目、SOP 等核心资产删除必须有 Dialog 二次确认拦截。
