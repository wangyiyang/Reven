import { describe, expect, it } from "vitest"

import { safeGithubUrl, safeNotionUrl } from "./external-url"

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

describe("safeGithubUrl", () => {
  it("expands owner/repo shorthand to a full URL", () => {
    expect(safeGithubUrl("wangyiyang/Reven")).toBe("https://github.com/wangyiyang/Reven")
  })

  it("keeps full HTTPS GitHub URLs", () => {
    expect(safeGithubUrl("https://github.com/wangyiyang/Reven")).toBe("https://github.com/wangyiyang/Reven")
    expect(safeGithubUrl("https://github.com/wangyiyang/Reven.git")).toBe("https://github.com/wangyiyang/Reven.git")
  })

  it.each(["bad url", "https://gitlab.com/wangyiyang/Reven", "javascript:alert(1)", "ftp://github.com/x/y"])(
    "rejects an unsafe GitHub value: %s",
    (value) => expect(safeGithubUrl(value)).toBeNull(),
  )
})
