import { describe, expect, test } from "vitest";

import { renderWechatHtml } from "../src/render";

describe("brand theme", () => {
  const html = renderWechatHtml(
    `## 二级标题\n\n正文带[链接](https://wangyiyang.cc)和\`inline code\`。\n\n> 引用一句话。\n\n\`\`\`ts\nconst x: number = 1 // 注释\n\`\`\`\n`,
  );

  test("headings stay carbon black without green fill", () => {
    expect(html).toMatch(/<h2[^>]*style="color:#0A0A0A;background:none/);
  });

  test("links use terminal green", () => {
    expect(html).toMatch(/<a[^>]*style="color:#00E676;font-weight:600/);
  });

  test("blockquote has green left bar and 5% gray background", () => {
    expect(html).toMatch(/<blockquote[^>]*style="[^"]*border-left:4px solid #00E676/);
    expect(html).toMatch(/<blockquote[^>]*style="[^"]*background:rgb\(10 10 10/);
  });

  test("code block uses dark background with green keywords", () => {
    expect(html).toMatch(/<pre[^>]*style="background:#0A0A0A/);
    expect(html).toMatch(/<span class="hljs-keyword" style="color:#00E676">/);
  });
});
