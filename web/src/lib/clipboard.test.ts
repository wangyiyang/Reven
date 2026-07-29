import { beforeEach, describe, expect, it, vi } from "vitest"

import { copyRichHtml } from "./clipboard"

describe("copyRichHtml", () => {
  beforeEach(() => {
    Object.defineProperty(window, "isSecureContext", { configurable: true, value: true })
  })

  it("writes text/html and text/plain clipboard flavors", async () => {
    const write = vi.fn().mockResolvedValue(undefined)
    class TestClipboardItem {
      types: string[]
      constructor(readonly data: Record<string, Blob>) {
        this.types = Object.keys(data)
      }
    }
    vi.stubGlobal("ClipboardItem", TestClipboardItem)
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { write } })

    await copyRichHtml("<h1>标题</h1>", "标题")

    expect(write.mock.calls[0][0][0].types).toEqual(["text/html", "text/plain"])
  })

  it("rejects insecure contexts without a plain-text fallback", async () => {
    Object.defineProperty(window, "isSecureContext", { configurable: true, value: false })
    await expect(copyRichHtml("<p>正文</p>", "正文")).rejects.toThrow("需要 HTTPS")
  })
})
