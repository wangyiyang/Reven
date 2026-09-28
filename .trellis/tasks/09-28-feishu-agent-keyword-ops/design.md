# Design — 飞书 Agent 关键词链路打通

## 改动地图

```
agent/tools_rss.py        # create/update 后调 refresh；create 返回命中数
agent/mcp_server.py       # register_rss_tools 注入 refresher（装配点）
app.py                    # create_agent_mcp_server 调用处传 refresher（已有 state 单例）
agent/dsh.patch.yml       # 删除确认 + 话术指令
tests/agent/test_tools_rss.py   # 扩展
tests/agent/test_dsh_patch.py   # 指令存在性断言
```

## 关键决策

### 1. refresher 注入路径

`register_rss_tools(mcp, session_factory)` 增加可选参数 `embedding_refresher`。`app.py` 装配顺序上 `rss_embedding_refresher`（app.py:207）先于 agent MCP server 创建，直接传入 state 单例；为 None 时工具跳过 refresh 并标注 pending（保持 seam 可测、无 embedder 环境可降级）。

### 2. 命中数估计

复用筛选同款向量与阈值：新词 embedding 与 `rss_items` 条目向量算余弦相似度，计数超过正向阈值者。实现前必读 `rss/screening.py` / `rss/screening_service.py` 的阈值来源（配置项还是常量），**禁止新造一套阈值**；若阈值逻辑耦合过重抽不出，降级方案 = 返回 `None` 并在响应标注不可用，不阻塞本任务主线（embedding 生效才是 bug 级）。

- 库为空 / embedder 不可用 / 阈值不可用 → 命中数字段返回 `None`，由 Agent 话术省略。
- 检索范围限定最近 N 天条目（与筛选窗口一致），避免全表扫。

### 3. 删除确认放在指令层而非代码层

已拍板：MCP 工具本身不加 confirm 参数（LLM 工具确认态不可靠），约束写进 patch 指令。验收用指令存在性测试，不模拟 LLM 行为。

### 4. 兼容性

`KeywordPayload` 增加可选字段（`hit_count`、`embedding_status`）是向后兼容变更；REST schema 不动。
