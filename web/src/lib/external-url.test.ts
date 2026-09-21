import { describe, expect, it } from "vitest"

import { safeGithubUrl } from "./external-url"

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
