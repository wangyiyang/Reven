export type Theme = "light" | "dark"

const STORAGE_KEY = "theme"

export function getTheme(): Theme {
  return document.documentElement.dataset.theme === "dark" ? "dark" : "light"
}

export function initTheme(): void {
  const stored = localStorage.getItem(STORAGE_KEY)
  const dark = stored === null
    ? window.matchMedia("(prefers-color-scheme: dark)").matches
    : stored === "dark"
  document.documentElement.dataset.theme = dark ? "dark" : "light"
}

export function toggleTheme(): Theme {
  const next: Theme = getTheme() === "dark" ? "light" : "dark"
  document.documentElement.dataset.theme = next
  localStorage.setItem(STORAGE_KEY, next)
  return next
}
