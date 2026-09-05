import { ApiError, apiRequest } from "@/lib/api"
import type {
  BlogTemplatePayload,
  BrandAsset,
  BrandProfile,
  BrandProfilePayload,
  ChannelTemplate,
  WeChatTemplatePayload,
} from "./types"

export async function fetchBrandProfile(): Promise<BrandProfile> {
  const value = await apiRequest<unknown>("/brand/profile")
  if (!isRecord(value)) throw new ApiError(200, "invalid_response", "品牌档案响应格式无效")
  return value as unknown as BrandProfile
}

export async function saveProfileDraft(payload: BrandProfilePayload): Promise<void> {
  await apiRequest("/brand/profile/draft", { method: "PUT", body: JSON.stringify(payload) })
}

export async function publishProfile(): Promise<void> {
  await apiRequest("/brand/profile/publish", { method: "POST" })
}

export async function fetchBrandAssets(): Promise<BrandAsset[]> {
  const value = await apiRequest<unknown>("/brand/assets")
  if (!Array.isArray(value)) throw new ApiError(200, "invalid_response", "素材列表响应格式无效")
  return value as BrandAsset[]
}

export async function uploadBrandAsset(file: File, label: string, purpose: string): Promise<void> {
  const params = new URLSearchParams({ label, purpose })
  const response = await fetch(`/api/brand/assets?${params}`, {
    method: "POST",
    headers: { "Content-Type": file.type || "application/octet-stream", "X-Reven-CSRF": "1" },
    body: file,
  })
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { message?: string } | null
    throw new ApiError(response.status, "upload_failed", body?.message ?? "素材上传失败")
  }
}

export async function updateBrandAsset(
  assetId: string,
  patch: { label?: string; enabled?: boolean },
): Promise<void> {
  await apiRequest(`/brand/assets/${assetId}`, { method: "PATCH", body: JSON.stringify(patch) })
}

export async function fetchChannelTemplate(channel: "wechat" | "blog"): Promise<ChannelTemplate> {
  const value = await apiRequest<unknown>(`/brand/templates/${channel}`)
  if (!isRecord(value)) throw new ApiError(200, "invalid_response", "渠道模板响应格式无效")
  return value as unknown as ChannelTemplate
}

export async function saveWeChatTemplateDraft(payload: WeChatTemplatePayload): Promise<void> {
  await apiRequest("/brand/templates/wechat/draft", { method: "PUT", body: JSON.stringify(payload) })
}

export async function saveBlogTemplateDraft(payload: BlogTemplatePayload): Promise<void> {
  await apiRequest("/brand/templates/blog/draft", { method: "PUT", body: JSON.stringify(payload) })
}

export async function publishChannelTemplate(channel: "wechat" | "blog"): Promise<void> {
  await apiRequest(`/brand/templates/${channel}/publish`, { method: "POST" })
}

export interface BrandImportRun {
  id: string
  status: string
  dry_run: boolean
  report: {
    brand_name?: string
    assets_imported?: number
    assets_reused?: number
    skipped?: { item: string; reason: string }[]
  }
  error: string | null
  created_at: string
  finished_at: string | null
}

export async function runNotionImport(dryRun: boolean): Promise<BrandImportRun> {
  const value = await apiRequest<unknown>("/brand/import/notion", {
    method: "POST",
    body: JSON.stringify({ dry_run: dryRun }),
  })
  if (!isRecord(value)) throw new ApiError(200, "invalid_response", "导入结果响应格式无效")
  return value as unknown as BrandImportRun
}

export async function fetchImportRuns(): Promise<BrandImportRun[]> {
  const value = await apiRequest<unknown>("/brand/import/runs")
  if (!Array.isArray(value)) throw new ApiError(200, "invalid_response", "导入记录响应格式无效")
  return value as BrandImportRun[]
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}
