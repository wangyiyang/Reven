import { ChevronDown, ChevronRight, LogOut, Moon, Sun, type LucideIcon } from "lucide-react"
import { useEffect, useRef, useState, type ReactNode } from "react"
import { NavLink, useLocation } from "react-router-dom"
import { Toaster } from "sonner"

import { apiRequest } from "@/lib/api"
import { getTheme, toggleTheme, type Theme } from "@/lib/theme"
import { cn } from "@/lib/utils"
import { routes, type RouteDef } from "@/routes"

const GROUP_OPEN_KEY_PREFIX = "reven:nav:group-open:"
// 旧版按 RSS 单例持久化的折叠偏好键，读取时一次性迁移到按 group id keyed 的新键
const LEGACY_GROUP_OPEN_KEYS: Record<string, string> = { "/rss": "reven:nav:rss-open" }

type NavEntry = RouteDef & { path: string; label: string; icon: LucideIcon }

function isNavEntry(def: RouteDef): def is NavEntry {
  return def.path !== undefined && def.label !== undefined && def.icon !== undefined
}

function navChildren(entry: NavEntry): NavEntry[] {
  return entry.children?.filter(isNavEntry) ?? []
}

// 主导航与路由注册表同源：带 label + icon 的条目即导航项，带导航子项的条目即分组
const NAV_ENTRIES = routes.filter(isNavEntry)
const NAV_GROUPS = NAV_ENTRIES.filter((entry) => navChildren(entry).length > 0)

// 折叠偏好：null 表示用户未手动操作过，此时跟随路由（分组内页面展开、其余收起）；
// 一旦手动 toggle 就按 group id 持久化到 localStorage，之后一律以存储值为准
function loadGroupOpenPreference(groupId: string): boolean | null {
  try {
    const stored = localStorage.getItem(GROUP_OPEN_KEY_PREFIX + groupId)
    if (stored !== null) return stored === "true"
    const legacyKey = LEGACY_GROUP_OPEN_KEYS[groupId]
    const legacy = legacyKey ? localStorage.getItem(legacyKey) : null
    if (legacy === null) return null
    const migrated = legacy === "true"
    saveGroupOpenPreference(groupId, migrated)
    localStorage.removeItem(legacyKey!)
    return migrated
  } catch {
    return null
  }
}

function saveGroupOpenPreference(groupId: string, open: boolean) {
  try {
    localStorage.setItem(GROUP_OPEN_KEY_PREFIX + groupId, String(open))
  } catch {
    // 隐私模式等存储不可用场景：仅保持会话内状态
  }
}

async function logout() {
  try {
    await apiRequest("/auth/logout", { method: "POST" })
  } catch {
    // 会话可能已失效，照常回到登录页
  }
  window.location.assign("/login")
}

export function AppShell({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>(getTheme)
  const location = useLocation()
  const navRef = useRef<HTMLElement>(null)
  const [canScrollRight, setCanScrollRight] = useState(false)
  const [openPreferences, setOpenPreferences] = useState<Record<string, boolean | null>>(() =>
    Object.fromEntries(NAV_GROUPS.map((group) => [group.path, loadGroupOpenPreference(group.path)])),
  )

  const isGroupActive = (group: NavEntry) =>
    navChildren(group).some((child) => location.pathname.startsWith(child.path))
  const groupOpen = (group: NavEntry) => openPreferences[group.path] ?? isGroupActive(group)

  const toggleGroup = (group: NavEntry) => {
    const next = !groupOpen(group)
    saveGroupOpenPreference(group.path, next)
    setOpenPreferences((current) => ({ ...current, [group.path]: next }))
  }

  // 路由切换后把激活的 tab 滚动进可视区（移动端横向 tab 条；只看可见的链接，跳过桌面端分组按钮）
  useEffect(() => {
    navRef.current
      ?.querySelector("a.nav-link.active")
      ?.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "center" })
  }, [location.pathname])

  // 移动端 tab 条溢出提示：还能右滑时显示渐隐 + 箭头，滑到底隐藏
  useEffect(() => {
    const nav = navRef.current
    if (!nav) return
    const update = () => setCanScrollRight(nav.scrollLeft + nav.clientWidth < nav.scrollWidth - 4)
    update()
    nav.addEventListener("scroll", update, { passive: true })
    const observer = new ResizeObserver(update)
    observer.observe(nav)
    return () => {
      nav.removeEventListener("scroll", update)
      observer.disconnect()
    }
  }, [])

  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[15rem_1fr]">
      <aside className="z-20 border-b border-[var(--line)] bg-[var(--panel)] lg:sticky lg:top-0 lg:h-screen lg:border-r lg:border-b-0">
        <div className="flex h-full flex-wrap items-center justify-between gap-x-3 gap-y-2 px-5 py-4 lg:flex-col lg:flex-nowrap lg:items-stretch lg:px-6 lg:py-8">
          <NavLink aria-label="Reven 首页" className="group flex items-center gap-2.5" to="/rss/candidates">
            <img alt="" className="h-8 w-8 dark:hidden" src="/brand/yixing-logo-v2-master.svg" />
            <img alt="" className="hidden h-8 w-8 dark:block" src="/brand/yixing-logo-v2-mono-white.svg" />
            <span className="text-xl font-semibold tracking-[-0.02em]">Reven</span>
          </NavLink>
          <div className="relative order-last w-full lg:order-none lg:my-auto lg:w-auto">
            <nav
              aria-label="内容工作台主导航"
              className="overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden lg:overflow-visible"
              ref={navRef}
            >
              <ul className="flex gap-1 lg:flex-col lg:gap-2">
                {NAV_ENTRIES.map((entry) => {
                  const children = navChildren(entry)
                  return (
                    <li className="shrink-0" key={entry.path}>
                      {children.length > 0 ? (
                        <NavGroup
                          active={children.some((child) => location.pathname.startsWith(child.path))}
                          entry={{ ...entry, children }}
                          onToggle={() => toggleGroup(entry)}
                          open={groupOpen(entry)}
                        />
                      ) : (
                        <NavLink
                          aria-label={entry.label}
                          className={({ isActive }) => cn(
                            "nav-link flex min-h-11 items-center gap-2 whitespace-nowrap px-3 text-sm font-semibold lg:gap-3",
                            isActive && "active",
                          )}
                          to={entry.path}
                        >
                          <entry.icon aria-hidden size={17} />
                          <span>{entry.label}</span>
                        </NavLink>
                      )}
                    </li>
                  )
                })}
              </ul>
            </nav>
            {/* 移动端右缘渐隐 + 箭头：仅当 tab 条还能右滑时显示，提示后面还有模块 */}
            {canScrollRight && (
              <>
                <div
                  aria-hidden
                  className="pointer-events-none absolute inset-y-0 right-0 w-14 bg-gradient-to-l from-[var(--panel)] via-[var(--panel)]/70 to-transparent lg:hidden"
                />
                <button
                  aria-label="还有更多模块，向右滑动查看"
                  className="absolute top-1/2 right-0.5 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-full border border-[var(--line)] bg-[var(--panel)] text-[var(--muted)] shadow-sm lg:hidden"
                  onClick={() => navRef.current?.scrollBy({ left: 220, behavior: "smooth" })}
                  type="button"
                >
                  <ChevronRight aria-hidden size={16} />
                </button>
              </>
            )}
          </div>
          <div className="flex gap-2 lg:gap-3">
            <button
              aria-label="退出登录"
              className="flex h-11 w-11 items-center justify-center gap-2 rounded-md border border-[var(--line)] bg-[var(--bg)] text-sm text-[var(--muted)] transition-colors hover:text-[var(--ink)] lg:h-9 lg:min-h-9 lg:w-fit lg:justify-start lg:px-3"
              onClick={() => void logout()}
              type="button"
            >
              <LogOut aria-hidden size={14} />
              <span className="hidden lg:inline">退出</span>
            </button>
            <button
              aria-label={theme === "dark" ? "切换到浅色模式" : "切换到深色模式"}
              className="flex h-11 w-11 items-center justify-center gap-2 rounded-md border border-[var(--line)] bg-[var(--bg)] text-sm text-[var(--muted)] transition-colors hover:text-[var(--ink)] lg:h-9 lg:min-h-9 lg:w-fit lg:justify-start lg:px-3"
              onClick={() => setTheme(toggleTheme())}
              type="button"
            >
              {theme === "dark" ? <Sun aria-hidden size={14} /> : <Moon aria-hidden size={14} />}
              <span className="hidden lg:inline">{theme === "dark" ? "浅色" : "深色"}</span>
            </button>
          </div>
        </div>
      </aside>
      <div className="min-w-0">{children}</div>
      <Toaster position="bottom-right" theme={theme} />
    </div>
  )
}

function NavGroup(props: {
  entry: { label: string; icon: LucideIcon; children: NavEntry[] }
  open: boolean
  active: boolean
  onToggle: () => void
}) {
  const { entry } = props
  const GroupIcon = entry.icon
  return (
    <>
      <button
        aria-expanded={props.open}
        aria-label={entry.label}
        className={cn(
          "nav-link nav-group-trigger hidden min-h-11 w-full items-center gap-2 whitespace-nowrap px-3 text-sm font-semibold lg:flex lg:gap-3",
          props.active && "active",
        )}
        onClick={props.onToggle}
        type="button"
      >
        <GroupIcon aria-hidden size={17} />
        <span>{entry.label}</span>
        <ChevronDown aria-hidden className={cn("ml-auto transition-transform", props.open && "rotate-180")} size={14} />
      </button>
      <ul className={cn(
        "flex gap-1 lg:ml-3 lg:flex-col lg:gap-2 lg:border-l lg:border-[var(--line)] lg:pl-3",
        !props.open && "lg:hidden",
      )}>
        {entry.children.map((child) => (
          <li className="shrink-0" key={child.path}>
            <NavLink
              aria-label={child.label}
              className={({ isActive }) => cn(
                "nav-link flex min-h-11 items-center gap-2 whitespace-nowrap px-3 text-sm font-semibold lg:gap-3",
                isActive && "active",
              )}
              to={child.path}
            >
              <child.icon aria-hidden size={17} />
              <span>{child.label}</span>
            </NavLink>
          </li>
        ))}
      </ul>
    </>
  )
}
