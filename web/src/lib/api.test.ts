import { afterEach, describe, expect, it, vi } from "vitest"

import { apiRequest } from "./api"

afterEach(() => {
  vi.unstubAllGlobals()
})

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
