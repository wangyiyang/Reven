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
