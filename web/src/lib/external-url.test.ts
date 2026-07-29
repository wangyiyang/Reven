import { describe, expect, it } from "vitest"

import { safeNotionUrl } from "./external-url"

describe("safeNotionUrl", () => {
  it("accepts official HTTPS Notion hosts", () => {
    expect(safeNotionUrl("https://www.notion.so/page")).toBe("https://www.notion.so/page")
    expect(safeNotionUrl("https://workspace.notion.site/page")).toBe("https://workspace.notion.site/page")
  })

  it.each(["javascript:alert(1)", "http://www.notion.so/page", "https://notion.so.example/page"])(
    "rejects an unsafe external URL: %s",
    (value) => expect(safeNotionUrl(value)).toBeNull(),
  )
})
