import { describe, expect, test } from "vitest";

import { renderWechatHtml } from "../src/render";

describe("renderWechatHtml", () => {
  test("renders a styled heading and preserves Reven asset placeholders", () => {
    const html = renderWechatHtml("# 标题\n\n![图](reven-asset://image/1)");

    expect(html).toContain("<h1");
    expect(html).toContain("标题");
    expect(html).toContain('src="reven-asset://image/1"');
    expect(html).toMatch(/style="[^"]+"/);
    expect(html).not.toContain("<script");
    expect(html).not.toContain("<style");
    expect(html).not.toContain("@media");
    expect(html).not.toContain("var(--");
  });

  test.each([
    ["script", '<script>alert("x")</script>'],
    ["event handler", '<img src="x" onerror="alert(1)">'],
    ["javascript URL", '<a href="javascript:alert(1)">链接</a>'],
  ])("removes active content from %s", (_name, markdown) => {
    const html = renderWechatHtml(markdown);

    expect(html.toLowerCase()).not.toContain("<script");
    expect(html.toLowerCase()).not.toContain("onerror");
    expect(html.toLowerCase()).not.toContain("javascript:");
  });

  test("is deterministic", () => {
    const markdown = "# 标题";
    expect(renderWechatHtml(markdown)).toBe(renderWechatHtml(markdown));
  });
});
