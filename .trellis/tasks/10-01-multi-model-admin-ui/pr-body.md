Closes #173

## 变更说明

实现 #173：Web 集成页 Agent LLM 卡片扩展为多模型管理界面，补齐所需后端 API。在 #163（PR #166）的多模型注册表与飞书 `/model` 切换之上，把附加模型的管理产品化（此前只能走裸 API 操作 `public_config.models[]`）。

**前端（`web/src/features/integrations/`）**

- 新增 `agent-llm-models-editor.tsx`：Agent LLM 卡片内的「模型列表」区——默认模型行（标注「默认」，在上方表单编辑）+ 附加模型行（「已停用」「独立密钥/共用默认密钥/待保存」徽标、base_url 展示）。
- **增删改/启停本地暂存，随「保存配置」统一提交** `models[]`：行内草稿表单（provider/model/base_url/启用开关/独立 API Key），空字段与重复 ref（含与默认模型冲突）前端拦截；删除走 ConfirmDialog；未保存更改有提示。
- **设默认即时生效**：`setDefaultModel` 调专用端点（服务端完成密钥交换，本地无法模拟）；有未保存更改时按钮禁用并给出提示。
- **行级单模型连接测试**：`testModel` 调 `POST .../test {model_ref}`，结果行内展示（成功延迟/失败原因），失败同时 toast；默认模型测试仍走原「测试连接」按钮（刷新卡片状态徽章）。
- **独立密钥零回显**：编辑表单 password 输入留空 = 不变，「清除独立密钥」勾选 → 提交空串；密钥只随 `secret.model_keys` 上行，断言 DOM 不渲染明文。
- controller 扩展 `testingModelRef`/`modelTests` 行内状态；`IntegrationAction` 新增 `set-default-model`/`test-model` 两个动作种类（busy 归属与动作锁沿用现有机制）。

**后端（`server/src/reven/`）**

- `PUT /api/integrations/agent-llm` 接受并校验 `public_config.models[]`（`AgentLlmModelEntry` strict schema：ref 互不重复、不得与默认 ref 重复、条数上限 16、base_url 沿用 HTTPS 校验），写回注册表，#166 的运行时与 `/model` 指令直接生效。
- **密钥 merge 语义**：`api_key` 可选（提供=替换默认密钥，未提供=保留）；新增 `secret.model_keys: dict[ref, key]` 合并写独立密钥，**空串 = 清除该模型独立密钥**（回落共用默认密钥）；保存时自动 prune 已不在 `models[]` 中的孤儿 `model_key:*` 键。其他 provider 的 PUT 行为零变化。
- **新增** `POST /api/integrations/agent-llm/default-model {ref}`：把附加模型提升为默认——与旧默认条目互换位置（旧默认降为启用状态的附加条目，保留其 base_url）；**密钥随交换流转**（独立 key 升格为 api_key，原 api_key 落为旧默认的 `model_key:<old_ref>` 或继续共用）；hint 同步重算；连接状态重置。未知 ref → 404，停用模型 → 409，已是默认 → 幂等返回。
- **单模型连接测试**：`POST /{provider}/test` 接受可选 body `{model_ref}`（仅 agent-llm，其他 provider 带 ref → 422 `MODEL_REF_UNSUPPORTED`）。默认 ref 复用行级测试并落行状态（与旧语义一致）；附加 ref 用「独立 key 回落默认 key + 该条目 base_url」跑适配器、**不落行状态**、返回 `AgentModelTestResponse{ref, success, message, latency_ms, tested_at}`；**停用模型可测**（先测通再启用的工作流）；失败 message 按已知密钥集合脱敏。
- **删除保护**：PUT 缩减 `models[]` 时，若被删 ref 正被某会话的 `/model` override 引用 → 409 `AGENT_MODEL_IN_USE`（附引用 ref 清单）。`FeishuChatDispatcher`/`FeishuBotSupervisor` 新增 `model_refs_in_use()` 只读快照接缝（override 字典仅主事件循环写入，路由同线程读取安全；supervisor 缺该能力时降级为空集）。
- 响应新增 `model_key_refs`（仅 agent-llm）：有独立密钥的附加模型 ref 列表，供 UI 渲染徽标；密文缺失/损坏时降级为 `null`，**任何响应永不包含密钥明文**。

**结构整理**：`AGENT_LLM_PROVIDER`/`DEFAULT_AGENT_LLM_*`/`model_ref_of` 从 `credentials.py` 下沉至 `providers.py`（打破 service→credentials 循环依赖，credentials 保留兼容再导出）。

## 设计决策

1. **列表编辑本地暂存 + 统一保存**：与卡片既有「保存配置」心智一致，误删可刷新恢复；「设默认」因涉及服务端密钥交换必须即时生效，故单独端点并在 dirty 时禁用，避免本地编辑被静默丢弃。
2. **密钥 merge 而非整体替换**：UI 的「替换默认密钥」不应顺带清空各模型独立 key；merge + prune 语义下，独立 key 生命周期完全跟随 `models[]` 数组。
3. **删除保护放后端**：前端只做友好提示，权威校验在服务端（ dispatcher 的内存 override 只有后端可见），409 由 UI toast 呈现。
4. **per-model 测试永远 200 + success 字段**：行级失败是预期结果而非请求失败，避免与全局错误 toast 通道混淆；默认模型 ref 复用同一端点并保持落行状态的旧语义。

## 测试结果

- `pytest server/tests`（TEST_DATABASE_URL 本地 PG）：**374 passed**（新增 15 个用例：models 写回/启停标志、ref 去重与默认冲突 422、坏 base_url/额外字段/缺字段 422、model_keys merge/清除/prune/明文不回显、设默认密钥交换/幂等/404/409、按 ref 测试默认落状态 vs 附加不落、停用模型可测、IN_USE 删除保护、dispatcher/supervisor in-use 快照）
- `ruff check` / `ruff format --check`：干净；`mypy server/src`：124 文件无问题
- `pnpm --filter @reven/web test`：**215 passed**（新增 9 个 UI 用例：列表徽标渲染、新增/编辑/删除/启停的暂存与保存负载、密钥零回显、行级测试成功与失败、设默认端点调用与 dirty 禁用）；`tsc -b` / `eslint` / `build`：干净

## 验收标准对照

- [x] 模型列表：默认 + 附加模型、启用状态、密钥状态徽标
- [x] 增删改：行内编辑 + 统一保存；删除需确认且被会话引用时服务端 409 拦截
- [x] 设默认：即时生效、密钥随交换流转、停用模型不可设（409）
- [x] 启停：本地切换随保存生效，停用模型从 `/model` 列表消失（#166 白名单语义）
- [x] 单模型连接测试：行内展示结果，停用模型亦可测
- [x] 凭证红线：独立密钥加密存储、只写不读、失败信息脱敏
