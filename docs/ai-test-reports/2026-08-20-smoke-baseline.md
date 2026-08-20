# Reven AI 冒烟巡检 Baseline（2026-08-20）

> 执行方式：按 `docs/ai-test-map.md` 的冒烟路径，用 agent-browser 登录 dev 做只读巡检。  
> 红线遵守：未创建/重置任何凭证；未做写操作；未造 `AITEST-` 数据。

## 1. 环境

| 项 | 值 |
|---|---|
| 站点 | `https://dev.wangyiyang.cc` |
| 运行版本 | main 运行时部署到 `f7360a0`（#51 内容区留白）；巡检时 repo main 为 `de55a75`（#52 测试地图，docs-only 不影响运行时） |
| 浏览器 | agent-browser session `reven-ai-smoke` |
| 登录 | 使用 Boss 提供的管理员密码，仅本次会话 |
| 范围 | ENV / AUTH / SHELL / 各模块只读 GET / 安全基线 |

## 2. 结果总览

| 区域 | 结论 | 备注 |
|---|---|---|
| 健康检查 | 通过 | `GET /api/health` → `{"service":"reven","status":"ok"}` |
| 登录/会话 | 通过 | 登录成功；`/api/auth/me` → `authenticated:true`；未登录 `GET /api/projects` → 401 `unauthorized` |
| 壳层导航 | 通过 | 8 个菜单入口均可达；未知路径 `/definitely-not-exists` 回 `/articles` |
| 内容区间距 | 通过 | `/finance` `/projects` `/playbooks` 已有页面容器，侧边栏与内容区不再贴边 |
| 稿件 | 通过 | `/articles` 渲染；`GET /api/articles?page=1` → 200，结构含 `items/page/page_size/total` |
| RSS | 通过 | candidates 200（1226 条）、sources 200（37）、keywords 200（75） |
| 集成 | 通过 | `GET /api/integrations` → 200；feishu/notion 均 `secret_configured:true`，只返回 hint |
| 财务 | 通过 | `/finance` 渲染；summary 200，当前全 0 |
| 项目库 | 通过 | `/projects` 渲染；`GET /api/projects` → 200，空列表 |
| SOP/话术 | 通过 | `/playbooks` 渲染；`GET /api/playbooks` → 200，空列表 |
| 系统状态 | 通过带观察 | database / notion_sync / scheduler available=true；egress-ip `available:false,ip:null` |

## 3. 页面路径核对

| 路径 | 实际 URL | 标题 | H1 |
|---|---|---|---|
| `/articles` | `/articles` | Reven · 编辑控制室 | 稿件 |
| `/finance` | `/finance` | Reven · 编辑控制室 | 财务收支 |
| `/projects` | `/projects` | Reven · 编辑控制室 | 项目库 |
| `/playbooks` | `/playbooks` | Reven · 编辑控制室 | SOP / 话术库 |
| `/rss/candidates` | `/rss/candidates` | Reven · 编辑控制室 | RSS 候选工作台 |
| `/rss` | `/rss` | Reven · 编辑控制室 | RSS 内容发现配置 |
| `/integrations` | `/integrations` | Reven · 编辑控制室 | 集成设置 |
| `/system` | `/system` | Reven · 编辑控制室 | 系统状态 |
| `/definitely-not-exists` | 回 `/articles` | Reven · 编辑控制室 | 稿件 |

## 4. API 只读核对

| API | 状态 | 结构/摘要 |
|---|---:|---|
| `/api/auth/me` | 200 | `authenticated:true` |
| `/api/system/status` | 200 | database / notion_sync / scheduler 均 available=true |
| `/api/system/egress-ip` | 200 | `available:false`,`ip:null` |
| `/api/articles?page=1` | 200 | `items,page,page_size,total` |
| `/api/rss/candidates` | 200 | list[1226] |
| `/api/rss/sources` | 200 | list[37] |
| `/api/rss/keywords` | 200 | list[75] |
| `/api/integrations` | 200 | list[2]；feishu/notion secret_configured=true，仅 hint |
| `/api/finance/summary` | 200 | income/expense/net/receivable/payable 全 0 |
| `/api/projects` | 200 | list[0] |
| `/api/playbooks` | 200 | list[0] |

## 5. 发现与建议

1. **观察项：出口 IP 当前不可用**  
   `/api/system/egress-ip` 返回 `available:false`。实现符合“失败不编造地址”，但如果后续微信发布依赖出口 IP 白名单，需要单独排查 provider/网络。

2. **新模块为空是预期，但空态要继续补齐**  
   `/projects`、`/playbooks` API 为空列表；页面可渲染。按测试地图，下一步应补更明显空态与引导（UI polish）。

3. **RSS 数据量已经不小**  
   candidates 1226、sources 37、keywords 75。后续 AI 测试不要全量遍历候选详情，优先抽样和路径验证，避免长时间滚动/截图。

4. **基线结论**  
   当前 main 部署可用于后续 AI 回归。建议把本报告作为 baseline；后续任何 UI/接口变更后，按 `docs/ai-test-map.md` 第 13 节执行流复跑冒烟。

## 6. 证据

- 临时证据（本会话机器）：`/tmp/reven_smoke_pages.tsv`、`/tmp/reven_smoke_api.json`、`/tmp/reven-smoke-system.png`
- 长期证据以本报告为准；截图不落仓库，避免二进制污染。
