import { afterEach, describe, expect, it, vi } from "vitest"

import { apiRequest } from "./api"

const originalLocation = Object.getOwnPropertyDescriptor(window, "location")

afterEach(() => {
  vi.unstubAllGlobals()
  if (originalLocation) Object.defineProperty(window, "location", originalLocation)
})

function stubLocation(pathname: string, search = "") {
  const assign = vi.fn()
  Object.defineProperty(window, "location", {
    configurable: true,
    value: { ...window.location, pathname, search, assign },
  })
  return assign
}

describe("apiRequest CSRF headers", () => {
  it("adds the CSRF header to unsafe methods", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('{"ok":true}'))
    vi.stubGlobal("fetch", fetchMock)

    await apiRequest("/probe", { method: "POST" })

    const init = fetchMock.mock.calls[0]?.[1] as RequestInit
    expect(new Headers(init.headers).get("X-Reven-CSRF")).toBe("1")
  })

  it("does not add the CSRF header to GET", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('{"ok":true}'))
    vi.stubGlobal("fetch", fetchMock)

    await apiRequest("/probe")

    const init = fetchMock.mock.calls[0]?.[1] as RequestInit
    expect(new Headers(init.headers).has("X-Reven-CSRF")).toBe(false)
  })
})

describe("apiRequest auth redirect", () => {
  it("redirects to /login on 401 for non-auth paths", async () => {
    const assign = stubLocation("/rss/candidates", "?status=saved")
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response('{"code":"unauthorized"}', { status: 401 })),
    )

    await expect(apiRequest("/rss/candidates")).rejects.toMatchObject({ status: 401 })
    expect(assign).toHaveBeenCalledWith("/login?next=%2Frss%2Fcandidates%3Fstatus%3Dsaved")
  })

  it("does not redirect on 401 from auth endpoints", async () => {
    const assign = stubLocation("/login")
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response('{"code":"invalid_credentials"}', { status: 401 })),
    )

    await expect(
      apiRequest("/auth/login", { method: "POST", body: "{}" }),
    ).rejects.toMatchObject({ status: 401, code: "invalid_credentials" })
    expect(assign).not.toHaveBeenCalled()
  })
})
