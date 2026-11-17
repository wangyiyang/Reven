export interface RssSource {
  id: string
  name: string
  feed_url: string
  enabled: boolean
  created_at: string
  updated_at: string
}

export type RssKeywordKind = "positive" | "negative"

export interface RssKeyword {
  id: string
  term: string
  kind: RssKeywordKind
  enabled: boolean
  created_at: string
  updated_at: string
}

/** Bitable 候选记录：record_id 为飞书侧记录标识（非 UUID），字段对应候选表九列。 */
export interface RssCandidate {
  record_id: string
  source_name: string
  url: string | null
  title: string
  summary: string
  published_at: string | null
  status: string
  matched_keywords: string[]
  archived_at: string | null
  dedupe_key: string
}

export type RssCandidateView = "candidate" | "saved"
