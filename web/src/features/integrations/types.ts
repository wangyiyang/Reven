export type Provider = "notion" | "github" | "wechat" | "feishu"

export interface Integration {
  provider: Provider
  public_config: Record<string, unknown>
  secret_configured: boolean
  secret_hint: string | null
  connection_status: string
  last_tested_at: string | null
  last_error: string | null
}

export interface FieldDefinition {
  key: string
  label: string
  placeholder?: string
  type?: "text" | "password"
}

export interface ProviderDefinition {
  provider: Provider
  number: string
  title: string
  eyebrow: string
  description: string
  publicFields: FieldDefinition[]
  secretField: FieldDefinition
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
    ],
    secretField: { key: "token", label: "Token", type: "password", placeholder: "输入新 Token" },
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
    secretField: { key: "token", label: "Token", type: "password", placeholder: "输入新 Token" },
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
    secretField: { key: "app_secret", label: "AppSecret", type: "password", placeholder: "输入新 AppSecret" },
  },
  {
    provider: "feishu",
    number: "04",
    title: "飞书",
    eyebrow: "结果通知",
    description: "发布任务结束后，向指定机器人报告完整结果。",
    publicFields: [{ key: "name", label: "通知名称", placeholder: "发布通知" }],
    secretField: { key: "webhook_url", label: "Webhook", type: "password", placeholder: "输入新 Webhook URL" },
  },
]
