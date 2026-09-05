import { useState, type FormEvent } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"

import { ApiError, apiRequest } from "@/lib/api"

export function LoginPage() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const [password, setPassword] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (pending) return
    setPending(true)
    setError(null)
    try {
      await apiRequest("/auth/login", { method: "POST", body: JSON.stringify({ password }) })
      const next = params.get("next")
      navigate(next?.startsWith("/") && !next.startsWith("//") ? next : "/articles", { replace: true })
    } catch (err) {
      setError(err instanceof ApiError && err.status === 429 ? "尝试次数过多，请稍后再试" : "密码错误")
    } finally {
      setPending(false)
    }
  }

  return (
    <main className="grid min-h-screen place-items-center px-6">
      <form
        className="page-enter w-full max-w-sm rounded-lg border border-[var(--line)] bg-[var(--bg)] p-8 shadow-sm"
        onSubmit={onSubmit}
      >
        <div className="flex items-center gap-2.5">
          <img alt="" className="h-8 w-8 dark:hidden" src="/brand/yixing-logo-v2-master.svg" />
          <img alt="" className="hidden h-8 w-8 dark:block" src="/brand/yixing-logo-v2-mono-white.svg" />
          <span className="text-xl font-semibold tracking-[-0.02em]">Reven</span>
        </div>
        <label className="mt-8 block text-sm font-semibold" htmlFor="admin-password">
          管理员密码
        </label>
        <input
          autoComplete="current-password"
          autoFocus
          className="mt-2 min-h-11 w-full rounded-md border border-[var(--line)] bg-[var(--bg)] px-3 outline-none focus:border-[var(--signal)]"
          id="admin-password"
          onChange={(event) => setPassword(event.target.value)}
          type="password"
          value={password}
        />
        {error && (
          <p className="mt-3 text-sm text-[var(--danger)]" role="alert">
            {error}
          </p>
        )}
        <button
          className="mt-6 min-h-11 w-full rounded-md border border-[var(--signal)] bg-[var(--signal)] text-sm font-semibold text-[var(--on-signal)] transition-transform hover:-translate-y-px active:translate-y-px! disabled:opacity-50"
          disabled={pending || password.length === 0}
          type="submit"
        >
          {pending ? "登录中…" : "登录"}
        </button>
      </form>
    </main>
  )
}
