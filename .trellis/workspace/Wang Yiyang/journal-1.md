# Journal - Wang Yiyang (Part 1)

> AI development session journal
> Started: 2026-09-19

---

## 2026-09-19 — conversational-ops（gh-119）实施完成

**任务**：`.trellis/tasks/09-19-conversational-ops`（飞书机器人候选稿审核推送 + 应用配置页面）

**关键决策**（grilling 两轮拍板）：
- 范围收敛：只做候选稿审核推送，关键词管理不做（推翻 issue 推荐范围）
- 事件接收用 WebSocket 长连接（lark-oapi ws.Client，推翻 issue 的 webhook 默认决策）
- 凭证走 integrations secrets + 前端配置页面；保存后进程内自动重连（不重启）

**实施**：五阶段全部完成，trellis-check 质量门通过。
- 阶段一：`CandidateReviewService` 核心层抽取 + `rss_items.review_pushed_at`（migration 0020）
- 阶段二：`feishu_bot` provider 五镜像面对齐 + 前端 integrations 新卡片
- 阶段三：`FeishuBotSupervisor` 长连接生命周期（SDK 只有阻塞 start/无公开 stop，尽力停止语义）
- 阶段四：审核卡片推送管道（≤10/卡分批，成功才标记 review_pushed_at）
- 阶段五：按钮回调（白名单硬门槛，404/409→"已处理"幂等 toast）

**check 修复**：dataclass 凭证字段 `repr=False`（对齐 translation 先例，spec 已补条款）、协程泄漏 close、连接测试补 bot/v1/info 拉取。

**遗留**：
- 真实飞书联调待人工前置（开放平台建应用、权限、open_id）
- `embedding/configuration.py` 的 api_key 同样缺 `repr=False`（既有遗漏，未在本任务范围）
- `tests/content_sync` 3 个用例既有 flaky（clean HEAD 复现，与本任务无关）
- 测试库容器 `reven-test-pg-119`（端口 55433）保留复用

