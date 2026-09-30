import type { RssRunHealth } from "./integration-api"

export type Provider =
  | "feishu_bot"
  | "translate_baidu" | "translate_aliyun" | "embedding" | "agent-llm"

/** 集成动作种类，与 integration-api 的 IntegrationAction.action 对齐 */
export type IntegrationActionKind = "save" | "delete" | "test" | "set-default-model" | "test-model"

export interface Integration {
  provider: Provider
  public_config: Record<string, unknown>
  secret_configured: boolean
  secret_hint: string | null
  connection_status: string
  last_tested_at: string | null
  last_error: string | null
  last_latency_ms: number | null
  /** 仅 agent-llm：配有独立密钥的附加模型 ref 列表（后端 2026-10 起返回，旧响应可能缺省） */
  model_key_refs?: string[] | null
}

/** agent-llm 附加模型条目（public_config.models[] 元素） */
export interface AgentModelEntry {
  provider: string
  model: string
  base_url?: string
  enabled: boolean
}

/** 单个模型的连接测试结果（POST /integrations/agent-llm/test {model_ref} 响应） */
export interface AgentModelTestResult {
  ref: string
  success: boolean
  message: string | null
  latency_ms: number | null
  tested_at: string
}

/** 行内展示的模型测试状态（卡片本地，不持久化） */
export interface ModelTestState {
  status: "ok" | "failed"
  message: string | null
  latencyMs: number | null
}

export interface FieldDefinition {
  key: string
  label: string
  placeholder?: string
  type?: "text" | "password" | "number" | "checkbox" | "string_list"
  optional?: boolean
  defaultValue?: string
}

export interface ProviderDefinition {
  provider: Provider
  number: string
  title: string
  eyebrow: string
  description: string
  publicFields: FieldDefinition[]
  secretFields: FieldDefinition[]
}

export const PROVIDERS: ProviderDefinition[] = [
  {
    provider: "feishu_bot",
    number: "01",
    title: "飞书应用",
    eyebrow: "通知与对话",
    description: "向白名单成员发送每日汇总（含待审核统计与候选工作台入口）；白名单成员可在飞书中与机器人对话，采纳 / 忽略在候选工作台完成。",
    publicFields: [
      { key: "whitelist_open_ids", label: "可使用机器人的用户 Open ID（通知接收 + 对话）", type: "string_list", optional: true, placeholder: "ou_…，每行一个或用逗号分隔" },
      { key: "enabled", label: "启用机器人", type: "checkbox" },
    ],
    secretFields: [
      { key: "app_id", label: "App ID", placeholder: "cli_…" },
      { key: "app_secret", label: "App Secret", type: "password", placeholder: "输入新 App Secret" },
    ],
  },
  {
    provider: "translate_baidu",
    number: "02",
    title: "百度翻译",
    eyebrow: "机器翻译",
    description: "专业机翻引擎，按优先级参与故障切换。",
    publicFields: [
      { key: "priority", label: "优先级", type: "number", defaultValue: "1" },
      { key: "enabled", label: "参与故障切换", type: "checkbox", defaultValue: "true" },
    ],
    secretFields: [
      { key: "app_id", label: "AppID", placeholder: "输入 AppID" },
      { key: "app_key", label: "密钥", type: "password", placeholder: "输入密钥" },
    ],
  },
  {
    provider: "translate_aliyun",
    number: "03",
    title: "阿里翻译",
    eyebrow: "机器翻译",
    description: "专业机翻引擎，按优先级参与故障切换。",
    publicFields: [
      { key: "priority", label: "优先级", type: "number", defaultValue: "1" },
      { key: "enabled", label: "参与故障切换", type: "checkbox", defaultValue: "true" },
    ],
    secretFields: [
      { key: "access_key_id", label: "AccessKey ID", placeholder: "输入 AccessKey ID" },
      { key: "access_key_secret", label: "AccessKey Secret", type: "password", placeholder: "输入 AccessKey Secret" },
    ],
  },
  {
    provider: "embedding",
    number: "04",
    title: "Embedding",
    eyebrow: "语义向量",
    description: "候选语义打分使用的向量服务，默认 SiliconFlow bge-m3，兼容 OpenAI 端点。",
    publicFields: [
      { key: "base_url", label: "Base URL", defaultValue: "https://api.siliconflow.cn" },
      { key: "model", label: "模型", defaultValue: "BAAI/bge-m3" },
    ],
    secretFields: [{ key: "api_key", label: "API Key", type: "password", placeholder: "输入 API Key" }],
  },
  {
    provider: "agent-llm",
    number: "05",
    title: "Agent LLM",
    eyebrow: "智能体",
    description: "Agent 核心的 LLM 推理服务，默认 DeepSeek，兼容 OpenAI 端点。",
    publicFields: [
      { key: "provider", label: "Provider", defaultValue: "deepseek-official" },
      { key: "model", label: "模型", defaultValue: "deepseek-v4-flash" },
      { key: "base_url", label: "Base URL", placeholder: "https://api.deepseek.com（可选）", optional: true },
    ],
    secretFields: [{ key: "api_key", label: "API Key", type: "password", placeholder: "输入 API Key" }],
  },
]

/**
 * 单个 provider 的卡片控制器：IntegrationCard 只消费 {definition, controller}。
 * 动作锁与 busy 判定收敛在 useIntegrationsController 内部，不向外泄漏。
 */
export interface ProviderController {
  state: {
    integration?: Integration
    runHealth?: RssRunHealth | null
    /** 全局动作锁：任一集成操作进行中时禁用全部卡片动作 */
    disabled: boolean
    /** 当前 provider 正在执行的动作；null 表示空闲 */
    busy: IntegrationActionKind | null
    /** 正在执行行级测试的模型 ref；null 表示无行级测试进行中 */
    testingModelRef: string | null
    /** 各模型最近一次行级测试结果（按 ref 索引，卡片本地状态） */
    modelTests: Record<string, ModelTestState>
  }
  actions: {
    save: (publicConfig: Record<string, unknown>, secret?: Record<string, unknown>) => void
    replace: (publicConfig: Record<string, unknown>, secret: Record<string, unknown>) => void
    /** 删除密钥；resolve 为是否成功，供卡片做焦点恢复 */
    remove: () => Promise<boolean>
    /** 测试连接：结果以 setQueryData 局部写回缓存，不触发整表 refetch（#179） */
    test: () => void
    /** 把附加模型设为默认（服务端完成密钥交换）；ref 为 provider/model */
    setDefaultModel: (ref: string) => void
    /** 对单个模型做连接测试（默认模型请用 test 以刷新卡片状态）；只读探测，不触碰缓存 */
    testModel: (ref: string) => void
  }
}
