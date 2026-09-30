# dsh 会话重启后无法恢复（session already exists）重试修复

关联 issue：#161

## Goal

修复飞书机器人对话的持久性故障：每次服务重启/发版后，所有历史飞书会话的新消息必然失败（`AGENT_CHAT_FAILED`，机器人回复兜底文案），且会话永久中毒，只能手动删会话目录恢复。

## Background

2026-09-30 生产实测定位（详见 issue #161）：

- 飞书桥接 `chat_dispatcher.py:176` 为每个会话生成固定 `session_id = feishu:<chat_id>:<open_id>`，且丢弃 `chat()` 返回的 session_id
- dsh SDK 无 resume API：`session/prompt` 对"磁盘上存在、进程内存中不存在"的会话报 `JsonRpcError: session "..." already exists`
- 进程重启后内存会话表清空 → 旧 session_id 全部中毒

关键约束（决定修复层选型）：桥接层无会话映射存储，若仅靠"重试时换新 id 并返回"，下一条消息桥接仍传旧 id，又会冲突——每轮都开新会话、上下文全丢。因此**别名映射必须常驻在 `AgentRuntime` 进程内**。

## Requirements

- `AgentRuntime` 新增进程内会话别名映射（dict）：`chat()` 入口先将外部 session_id 翻译为活跃 id
- `chat()` 捕获 `HarnessError` 中消息含 "already exists" 的 `JsonRpcError`，为该外部 id 生成新活跃 id（如 `f"{session_id}~r{uuid4().hex[:8]}"`），记录别名并重试一次；重试仍失败则按原路径抛 `AgentRuntimeError`
- 返回值语义不变：`(实际使用的 session_id, 响应文本)`
- 别名映射进程内有效即可（重启后映射清空，首次冲突会再触发一次重试 mint，符合预期）；无需持久化、无需清理磁盘旧目录
- 不改 `chat_dispatcher.py`（桥接层保持现状）；不改 SDK；不引入新依赖

## Acceptance Criteria

- [ ] 进程重启后，历史飞书会话发新消息自动恢复对话（无需手动删 `/data/dsh/sessions/` 目录）
- [ ] 同一外部 session_id 的后续消息沿用同一活跃 id（对话上下文在进程生命周期内连续，不会每轮开新会话）
- [ ] 新增测试覆盖：already exists → mint 新 id + 记别名 + 重试成功 → 后续同 id 直接命中别名；重试仍失败 → 抛 AGENT_CHAT_FAILED
- [ ] `uv run pytest tests/` 全绿，`ruff check` / `ruff format --check` / mypy 干净
