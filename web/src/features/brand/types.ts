export interface BrandColors {
  primary: string
  text: string
  background: string
}

export interface BrandFonts {
  body: string
  mono: string
}

export interface BrandProfilePayload {
  brand_name: string
  intro: string
  default_author: string
  handle: string
  website: string
  tagline: string
  colors: BrandColors
  fonts: BrandFonts
  style_notes: string
}

export interface BrandVersion {
  id: string
  version: number
  status: string
  payload: BrandProfilePayload
  source: string
  published_at: string | null
  created_at: string
  updated_at: string
}

export interface BrandProfile {
  published: BrandVersion | null
  draft: BrandVersion | null
}

export interface BrandAsset {
  id: string
  purpose: string
  label: string
  enabled: boolean
  public_url: string
  sha256: string
  mime_type: string
  byte_size: number
  width: number | null
  height: number | null
  source: string
  created_at: string
}

export interface FooterModule {
  key: string
  type: "text" | "image"
  content: string
  asset_id: string | null
  enabled: boolean
}

export interface WeChatTheme {
  primary_color: string
  font_family: string
  font_size: number
}

export interface WeChatTemplatePayload {
  theme: WeChatTheme
  footer_modules: FooterModule[]
}

export interface BlogTemplatePayload {
  author: string
  cover_fallback_asset_id: string | null
  og_image_asset_id: string | null
}

export interface TemplateVersion {
  id: string
  channel: string
  version: number
  status: string
  payload: Record<string, unknown>
  published_at: string | null
  created_at: string
  updated_at: string
}

export interface ChannelTemplate {
  published: TemplateVersion | null
  draft: TemplateVersion | null
}

export const ASSET_PURPOSES = ["标志", "头像", "二维码", "封面", "其他"] as const

export const DEFAULT_PROFILE: BrandProfilePayload = {
  brand_name: "",
  intro: "",
  default_author: "",
  handle: "",
  website: "",
  tagline: "",
  colors: { primary: "#00E676", text: "#0A0A0A", background: "#FAFAFA" },
  fonts: { body: "", mono: "" },
  style_notes: "",
}

export const DEFAULT_WECHAT_TEMPLATE: WeChatTemplatePayload = {
  theme: { primary_color: "#00E676", font_family: "", font_size: 16 },
  footer_modules: [],
}

export const DEFAULT_BLOG_TEMPLATE: BlogTemplatePayload = {
  author: "",
  cover_fallback_asset_id: null,
  og_image_asset_id: null,
}
