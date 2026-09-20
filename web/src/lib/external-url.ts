const GITHUB_HOSTS = new Set(["github.com", "www.github.com"])
const GITHUB_REPO_SHORTHAND = /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/

export function safeGithubUrl(value: string): string | null {
  const trimmed = value.trim()
  if (GITHUB_REPO_SHORTHAND.test(trimmed)) {
    return `https://github.com/${trimmed}`
  }
  try {
    const url = new URL(trimmed)
    return url.protocol === "https:" && GITHUB_HOSTS.has(url.hostname) ? url.href : null
  } catch {
    return null
  }
}
