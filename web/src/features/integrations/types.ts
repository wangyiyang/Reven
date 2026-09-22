import type { RssRunHealth } from "./integration-api"

export type Provider =
  | "feishu_bot"
  | "translate_baidu" | "translate_aliyun" | "embedding" | "agent-llm"

/** 集成动作种类，与 integration-api 的 IntegrationAction.action 对齐 */
export type IntegrationActionKind = "save" | "delete" | "test"

export interface Integration {
  provider: Provider
  public_config: Record<string, unknown>
  secret_configured: boolean
  secret_hint: string | null
  connection_status: string
  last_tested_at: string | null
  last_error: string | null
  last_latency_ms: number | null
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
    eyebrow: "通知与审核",
    description: "向白名单成员发送每日汇总和候选素材审核卡片，在飞书内完成采纳 / 忽略。",
    publicFields: [
      { key: "whitelist_open_ids", label: "接收人 Open ID（审核白名单）", type: "string_list", optional: true, placeholder: "ou_…，每行一个或用逗号分隔" },
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
  }
  actions: {
    save: (publicConfig: Record<string, unknown>) => void
    replace: (publicConfig: Record<string, unknown>, secret: Record<string, string>) => void
    /** 删除密钥；resolve 为是否成功，供卡片做焦点恢复 */
    remove: () => Promise<boolean>
    test: () => void
  }
}
