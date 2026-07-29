const NOTION_HOSTS = new Set(["notion.so", "www.notion.so"])

export function safeNotionUrl(value: string): string | null {
  try {
    const url = new URL(value)
    const trustedHost = NOTION_HOSTS.has(url.hostname) || url.hostname.endsWith(".notion.site")
    return url.protocol === "https:" && trustedHost ? url.href : null
  } catch {
    return null
  }
}
