export type ChannelName = "个人博客" | "微信公众号"

export interface ContentSyncRun {
  id: string
  article_id: string
  status: string
  stage: string
  progress_current: number
  progress_total: number
  current_media: string | null
  error_stage: string | null
  error_code: string | null
  error_message: string | null
  error_media: string | null
  retryable: boolean
  attempt_count: number
  created_at: string
  updated_at: string
  created: boolean | null
}

export interface CurrentSnapshotSummary {
  id: string
  synced_at: string
  source_last_edited_at: string
  content_hash: string
  character_count: number
  media_count: number
}

export interface ContentSyncSummary {
  status: string
  outputs_enabled: boolean
  error: string | null
  current_snapshot: CurrentSnapshotSummary | null
  latest_run: ContentSyncRun | null
}

export interface ArticleSummary {
  id: string
  title: string
  notion_url: string
  notion_status: string
  automation_status: string
  /** Notion 目标渠道多选的原始值，可能包含发布链路不支持的渠道（如「掘金」），仅用于展示 */
  target_channels: string[]
  planned_at: string | null
  notion_last_edited_at: string
  last_synced_at: string
  cover_valid: boolean
  content_sync: ContentSyncSummary
  blog_status: string | null
  wechat_status: string | null
}

export interface ArticleList {
  items: ArticleSummary[]
  total: number
  page: number
  page_size: number
}

export interface JobSummary {
  id: string
  overall_status: string
  target_channels: ChannelName[]
  scheduled_at: string
  content_hash: string | null
  blog_status: string
  wechat_status: string
}

export interface ChannelResult {
  status: string
  error: string | null
  result: Record<string, string | number>
}

export interface JobBrand {
  binding_key: string
  version_fingerprint: {
    brand_version?: number
    wechat_template_version?: number | null
    blog_template_version?: number | null
  }
}

export interface ArticleDetail extends ArticleSummary {
  notion_url: string
  notion_metadata: Record<string, unknown>
  cover_metadata: Record<string, unknown>
  selected_cover_asset_id: string | null
  last_error: string | null
  content_hash: string | null
  validation_errors: ValidationItem[]
  validation_warnings: ValidationItem[]
  blog: ChannelResult | null
  wechat: ChannelResult | null
  jobs: JobSummary[]
  jobs_total: number
  jobs_has_more: boolean
}

export interface JobDetail extends JobSummary {
  article_id: string
  brand_binding_key: string
  brand: JobBrand | null
  snapshot_metadata: Record<string, unknown>
  blog: ChannelResult
  wechat: ChannelResult
  wechat_html: string | null
  attempt_count: number
  created_at: string
  updated_at: string
}

export interface ValidationItem {
  code?: string
  field?: string
  message?: string
}
