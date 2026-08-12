export type Theme = "light" | "dark"

const STORAGE_KEY = "theme"

export function getTheme(): Theme {
  return document.documentElement.dataset.theme === "dark" ? "dark" : "light"
}

function readStoredTheme(): Theme | null {
  try {
    const value = localStorage.getItem(STORAGE_KEY)
    return value === "dark" || value === "light" ? value : null
  } catch {
    return null
  }
}

export function initTheme(): void {
  const stored = readStoredTheme()
  const dark = stored === null
    ? window.matchMedia("(prefers-color-scheme: dark)").matches
    : stored === "dark"
  document.documentElement.dataset.theme = dark ? "dark" : "light"
}

export function toggleTheme(): Theme {
  const next: Theme = getTheme() === "dark" ? "light" : "dark"
  document.documentElement.dataset.theme = next
  try {
    localStorage.setItem(STORAGE_KEY, next)
  } catch {
    // 存储不可用时仅本次会话生效
  }
  return next
}
