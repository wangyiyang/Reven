# 审视范围依据

- 日期：2026-10-01（Asia/Shanghai）。
- 基线：main / 2a0fc6188ab2435d271c3933f5cc7f32ef9890e8。
- 先查最近 70 个提交，再以最近 25 个提交校准，优先新变更。
- 主线最近新增多模型选择、dsh 重启恢复、CRM MCP 工具与定时主动推送；因此本轮聚焦 Agent / 飞书对话 / 定时提醒。
- GLOSSARY.md 和 docs/adr/ 缺失；沿用 docs/agent-architecture.md 与 Trellis 领域契约。
- 09-22 已完成凭证、Settings、连接测试、Web CRUD 和路由深化，本轮不重复立项。

## 最近 70 个提交的源码路径频次

| 次数 | 路径 |
| --- | --- |
| 14 | `server/src/reven/app.py` |
| 11 | `web/src/components/app-shell.tsx` |
| 9 | `web/src/features/integrations/types.ts` |
| 9 | `web/src/components/app-shell.test.tsx` |
| 8 | `server/src/reven/config.py` |
| 8 | `server/src/reven/api/routes/integrations.py` |
| 8 | `web/src/app.tsx` |
| 7 | `server/src/reven/integrations/feishu_bot/client.py` |
| 7 | `server/src/reven/rss/factory.py` |
| 7 | `web/src/features/integrations/integrations-page.test.tsx` |
| 7 | `server/src/reven/integrations/service.py` |
| 6 | `web/src/features/integrations/integration-card.tsx` |
| 6 | `server/src/reven/api/schemas/integrations.py` |
| 5 | `server/src/reven/integrations/feishu_bot/handlers.py` |
| 5 | `server/src/reven/integrations/providers.py` |
| 5 | `web/src/features/integrations/integration-api.ts` |
| 4 | `server/src/reven/agent/config.py` |
| 4 | `server/src/reven/integrations/feishu_bot/supervisor.py` |
| 4 | `server/src/reven/integrations/feishu_bot/review_callback.py` |
| 4 | `server/src/reven/integrations/feishu_bot/review_pusher.py` |

频次只是选取审视范围的依据，不代表模块质量或深浅。现有 uv.lock 改动不属于本任务。
