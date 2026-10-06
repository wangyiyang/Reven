# 多模型管理 UI（#173）

## 背景

#163（PR #166）交付了多模型注册表与飞书 /model 切换，当时把「多模型管理 UI」划为后续。目前附加模型只能走 API 操作 public_config.models[]，需产品化。

## 需求（issue #173）

Web 集成页 Agent LLM 卡片扩展为多模型管理界面：

1. **模型列表**：展示默认模型 + models[] 附加模型（provider/model/base_url/是否启用/是否默认）
2. **增删改**：新增模型、编辑、删除（删除前确认；引用中的模型禁删或提示）
3. **设默认**：一键把某模型设为默认
4. **启停**：enabled 开关（停用后 /model list 不再出现）
5. **连接测试**：对任意单个模型做连通性测试（现成测试接缝，需支持指定模型条目）

后端：

- integrations API 支持 models[] 数组的读取与写回
- 连接测试支持按模型 ref 指定（缺省测默认）
- 凭证红线：api_key 只进 encrypted_secret，前端永不回显；附加模型 key 走 `model_key:<ref>` 扁平键（#166 约定）

## 验收

- [ ] Web 界面完成上述 5 项，全程无需碰 API
- [ ] /model list 即时反映启停与增删
- [ ] 密钥零回显（含接口响应）
- [ ] 前后端测试齐备，CI 全绿

## 设计决策

### API 形状（复用现有单 PUT 架子，最小新增端点）

- `PUT /api/integrations/agent-llm`：public_config 增加 `models[]`（strict entry：provider/model/base_url?/enabled=true；
  ref 互不相同且不等于默认 ref，上限 16 条）；secret 增加可选 `model_keys: {ref: key}`（空串=清除该模型
  独立 key），`api_key` 变为可选——agent-llm 走 merge 语义（保留未提及的 key），其他 provider 行为不变。
  每次 PUT 自动 prune 掉不再被 models[] 引用的 `model_key:*`。
  删除保护：被飞书会话 override 引用中的模型从 models[] 移除时返回 409 AGENT_MODEL_IN_USE。
- `POST /api/integrations/agent-llm/default-model` `{ref}`：服务端完成默认交换（含 key 材料互换，
  前端永远接触不到明文），旧默认回落为启用的附加条目；禁用条目 409，未知 ref 404，幂等。
- `POST /api/integrations/agent-llm/test` `{model_ref?}`：缺省/默认 ref 维持现状（落行状态，
  IntegrationResponse）；附加模型 ref 返回 `AgentModelTestResponse{ref,success,message,latency_ms,tested_at}`，
  不动行状态（禁用条目也可测，先测后启用）。
- `IntegrationResponse` 增加 `model_key_refs: list[str] | null`（仅 agent-llm：有独立 key 的附加模型 ref），
  供 UI 展示「独立密钥 / 共用默认密钥」；明文永不回显。

### 前端

- Agent LLM 卡片内嵌 `AgentLlmModelsEditor`：默认模型行（顶层字段，现有表单）+ 附加模型列表。
- 增/删/改/启停 = 本地暂存，随「保存配置」一次性 PUT（含 pending model_keys）；删除有 ConfirmDialog。
- 设默认 = 即时调专用端点（服务端换 key）；有未保存 models 更改时禁用。
- 行级连接测试即时调用，结果行内展示（默认行走原 test 语义）。

### in-use 接缝

- `FeishuChatDispatcher.model_refs_in_use()` 返回 override ref 快照（只主循环读写，路由同线程安全）；
  supervisor 委托暴露；route 以 getattr 降级（无 supervisor = 空集）。
