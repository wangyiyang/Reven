# 飞书 Agent 对话维护 RSS 关键词链路打通

> 来源：GitHub Issue #153（2026-09-28 拷问收敛）。任务 09-19-conversational-ops 的后续增量。

## Goal

让"飞书里对机器人说人话增删 RSS 关键词"这条链路真正可用：词入库即生成 embedding 生效，加词后有命中数即时反馈，删除有复述确认。

## Background

- Agent 已自带 `rss_keyword_create/list/update/delete` 四个 MCP 工具（`agent/tools_rss.py`），但**只写库不生成 embedding**；筛选走 BGE-M3 语义向量，无 embedding 的词静默不生效（REST 侧靠 `/embeddings/rebuild` 单独触发，Agent 路径无人触发）——bug 级缺口。
- 需求形态已拍板：Agent 自然语言对话，不做固定指令。真实场景是刷到热点随手加/删词。

## Requirements

1. **生效缺口修复**：`rss_keyword_create` / `rss_keyword_update` 成功后触发 `RssEmbeddingRefresher.refresh()`（增量，仅补缺失/hash 变化词）。embedding 生成失败时工具仍返回成功但响应标注 `embedding_pending`（词已入库，下轮调度/手动 rebuild 兜底），不静默。
2. **命中数回报**：`rss_keyword_create` 响应附带该词对当前条目库的命中数估计（复用筛选阈值语义的向量检索），供 Agent 话术引用。
3. **Agent 行为约束**（`agent/dsh.patch.yml` 或 profile 指令层）：
   - 删除关键词前必须复述确认（词、正/反向、ID），用户确认后才调 `rss_keyword_delete`；停用/启用无需确认。
   - 增/删/改后回复话术必须包含：按语义匹配生效（非精确匹配）、下次每日抓取后生效、命中数（加词场景）。
4. **核心层一致性**：MCP 写路径与 REST 路由共用 `RssSettingsRepository` 冲突语义（现状已满足，保持）。

## Acceptance Criteria

- [ ] MCP create/update 后关键词 embedding 落库（增量 refresh 被调用且有测试断言）；embedder 不可用时工具返回成功但带 pending 标注
- [ ] create 响应含命中数估计字段（含库为空/无命中时为 0 的语义）
- [ ] patch 指令包含删除复述确认与话术三要素；`test_dsh_patch.py` 风格测试覆盖指令存在性
- [ ] server 测试全绿；新增用例覆盖：create 触发 refresh、refresh 失败降级、命中数计算、冲突提示
- [ ] 生产验证（合并后人工）：飞书发"增加正向关键词 具身智能"，机器人回命中数与生效说明；`rss_keywords` 表该词 embedding 非空

## Out of Scope

固定指令解析；精确匹配开关；sources 管理；历史候选重筛；多租户权限；delete 也触发全量 rebuild（删除的词向量残留不影响新条目筛选）。

## Notes

- `RssEmbeddingRefresher.refresh(force=False)` 已是增量语义（`rss/embedding.py:137`），装配于 `app.state.rss_embedding_refresher`（app.py:207）。
- MCP server 装配：`create_agent_mcp_server` → `register_rss_tools(mcp, session_factory)`（`agent/mcp_server.py`），refresher 需从此处注入。
- 现有测试样板：`server/tests/agent/test_tools_rss.py`。
