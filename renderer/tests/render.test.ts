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

  test.each([
    ["URL", "background:url(javascript:alert(1))"],
    ["mixed-case URL", "background:URL(  JaVaScRiPt:alert(1))"],
    ["escaped URL", String.raw`background:u\72l(javascript:alert(1))`],
    ["comment-obfuscated URL", "background:u/**/rl(javascript:alert(1))"],
    ["expression", "width:expression(alert(1))"],
    ["escaped expression", String.raw`width:exp\72 ession(alert(1))`],
    ["import", "@import url(https://evil.invalid/a.css)"],
    ["behavior", "behavior:url(xss.htc)"],
    ["binding", "-moz-binding:url(https://evil.invalid/xss.xml)"],
  ])("removes active CSS from %s", (_name, style) => {
    const html = renderWechatHtml(`<p style="${style}">正文</p>`);

    expect(html).not.toContain(style);
    expect(html.toLowerCase()).not.toContain("javascript:");
    expect(html.toLowerCase()).not.toContain("expression");
    expect(html.toLowerCase()).not.toContain("@import");
    expect(html.toLowerCase()).not.toContain("behavior:");
    expect(html.toLowerCase()).not.toContain("-moz-binding");
  });

  test("preserves safe inline CSS declarations", () => {
    const html = renderWechatHtml('<p style="color: red; font-size: 16px; margin: 4px">正文</p>');

    expect(html).toContain("color:red");
    expect(html).toContain("font-size:16px");
    expect(html).toContain("margin:4px");
  });

  test("restores only asset sources registered during this render", () => {
    const assetOne = Buffer.from("reven-asset://image/1").toString("base64url");
    const assetTwo = Buffer.from("reven-asset://image/2").toString("base64url");
    const markdown = [
      "![一](reven-asset://image/1)",
      "![二](reven-asset://image/2)",
      `[链接](https://reven.invalid/assets/${assetOne})`,
      `<img src="https://reven.invalid/assets/invalid">`,
      `<img src="https://reven.invalid/assets/${assetTwo}">`,
    ].join("\n\n");
    const html = renderWechatHtml(markdown);

    expect(html.match(/src="reven-asset:\/\/image\/1"/g)).toHaveLength(1);
    expect(html.match(/src="reven-asset:\/\/image\/2"/g)).toHaveLength(1);
    expect(html).toContain(`href="https://reven.invalid/assets/${assetOne}"`);
    expect(html).toContain('src="https://reven.invalid/assets/invalid"');
    expect(html).toContain(`src="https://reven.invalid/assets/${assetTwo}"`);
  });

  test("is deterministic", () => {
    const markdown = "# 标题\n\n![图](reven-asset://image/1)";
    expect(renderWechatHtml(markdown)).toBe(renderWechatHtml(markdown));
  });
});
