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

export interface RssCandidate {
  id: string
  source_name: string
  url: string | null
  title: string
  summary: string
  title_zh: string
  summary_zh: string
  published_at: string | null
  status: string
  positive_literal_matches: string[]
  negative_literal_matches: string[]
  bm25_score: number
  positive_embedding_score: number
  negative_embedding_score: number
  embedding_model: string | null
  embedding_status: string
  model_status: string
  model_score: number | null
  reason: string | null
  rules_version: string | null
  screening_error: string | null
  saved_at: string | null
}

export type RssCandidateView = "candidate" | "saved"
