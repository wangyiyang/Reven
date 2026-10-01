import type { AgentModelEntry } from "./types"

/** 把 public_config.models 原始值规范化为可编辑条目（畸形项静默剔除） */
export function parseModelEntries(raw: unknown): AgentModelEntry[] {
  if (!Array.isArray(raw)) return []
  return raw.flatMap((item) => {
    if (typeof item !== "object" || item === null || Array.isArray(item)) return []
    const record = item as Record<string, unknown>
    const provider = typeof record.provider === "string" ? record.provider.trim() : ""
    const model = typeof record.model === "string" ? record.model.trim() : ""
    if (!provider || !model) return []
    const baseUrl = typeof record.base_url === "string" ? record.base_url.trim() : ""
    return [{
      provider,
      model,
      ...(baseUrl ? { base_url: baseUrl } : {}),
      enabled: record.enabled !== false,
    }]
  })
}

/** 保存负载用的 models[]（base_url 缺省不携带，enabled 显式携带） */
export function modelEntriesForSave(models: AgentModelEntry[]): Record<string, unknown>[] {
  return models.map((entry) => ({
    provider: entry.provider,
    model: entry.model,
    ...(entry.base_url ? { base_url: entry.base_url } : {}),
    enabled: entry.enabled,
  }))
}

/** 模型引用：`provider/model` 主键格式（与后端 model_ref_of 对齐） */
export function modelRefOf(provider: string, model: string): string {
  return `${provider}/${model}`
}
