export type Provider =
  | "notion" | "github" | "wechat" | "feishu"
  | "translate_baidu" | "translate_aliyun" | "embedding"

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
  type?: "text" | "password" | "number" | "checkbox"
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
    provider: "notion",
    number: "01",
    title: "Notion",
    eyebrow: "稿件来源",
    description: "读取稿件库，并在发布前同步最新正文与封面。",
    publicFields: [
      { key: "database_id", label: "Database ID", placeholder: "3301a325-…" },
      { key: "data_source_id", label: "Data Source ID", placeholder: "4f7889bf-…" },
      { key: "inbox_data_source_id", label: "Inbox Data Source ID", placeholder: "素材 Inbox（可选）", optional: true },
    ],
    secretFields: [{ key: "token", label: "Token", type: "password", placeholder: "输入新 Token" }],
  },
  {
    provider: "github",
    number: "02",
    title: "GitHub",
    eyebrow: "博客发布",
    description: "通过分支、校验和 Pull Request 将稿件发布到博客。",
    publicFields: [
      { key: "owner", label: "Owner", placeholder: "wangyiyang" },
      { key: "repo", label: "Repo", placeholder: "wangyiyang.github.io" },
      { key: "default_branch", label: "默认分支策略", placeholder: "master" },
    ],
    secretFields: [{ key: "token", label: "Token", type: "password", placeholder: "输入新 Token" }],
  },
  {
    provider: "wechat",
    number: "03",
    title: "微信",
    eyebrow: "草稿生成",
    description: "上传素材并生成公众号草稿；不会自动群发。",
    publicFields: [
      { key: "app_id", label: "AppID", placeholder: "wx…" },
      { key: "author", label: "作者", placeholder: "王翊仰" },
    ],
    secretFields: [{ key: "app_secret", label: "AppSecret", type: "password", placeholder: "输入新 AppSecret" }],
  },
  {
    provider: "feishu",
    number: "04",
    title: "飞书",
    eyebrow: "结果通知",
    description: "发布任务结束后，向指定机器人报告完整结果。",
    publicFields: [{ key: "name", label: "通知名称", placeholder: "发布通知" }],
    secretFields: [{ key: "webhook_url", label: "Webhook", type: "password", placeholder: "输入新 Webhook URL" }],
  },
  {
    provider: "translate_baidu",
    number: "05",
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
    number: "06",
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
    number: "07",
    title: "Embedding",
    eyebrow: "语义向量",
    description: "候选语义打分使用的向量服务，默认 SiliconFlow bge-m3，兼容 OpenAI 端点。",
    publicFields: [
      { key: "base_url", label: "Base URL", defaultValue: "https://api.siliconflow.cn" },
      { key: "model", label: "模型", defaultValue: "BAAI/bge-m3" },
    ],
    secretFields: [{ key: "api_key", label: "API Key", type: "password", placeholder: "输入 API Key" }],
  },
]
