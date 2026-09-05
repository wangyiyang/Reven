import { describe, expect, test } from "vitest";

import { renderWechatHtml } from "../src/render";

const SAMPLE = "正文带[链接](https://wangyiyang.cc)。\n\n> 引用一句话。\n";

describe("renderWechatHtml theme", () => {
  test("不传 theme 时使用默认品牌色（与既有输出一致）", () => {
    const html = renderWechatHtml(SAMPLE);
    expect(html).toMatch(/<a[^>]*style="color:#00E676/);
    expect(html).toMatch(/<blockquote[^>]*style="[^"]*border-left:4px solid #00E676/);
  });

  test("自定义 primaryColor 替换链接与引用条颜色", () => {
    const html = renderWechatHtml(SAMPLE, { primaryColor: "#FF6600" });
    expect(html).toMatch(/<a[^>]*style="color:#FF6600/);
    expect(html).toMatch(/<blockquote[^>]*style="[^"]*border-left:4px solid #FF6600/);
    expect(html).not.toContain("#00E676");
  });

  test("自定义 fontFamily 与 fontSize 进入正文样式", () => {
    const html = renderWechatHtml("正文。", { fontFamily: "Georgia, serif", fontSize: 18 });
    expect(html).toContain("font-family:Georgia,serif");
    expect(html).toContain("font-size:18px");
  });

  test.each([
    ["非法颜色", { primaryColor: "red" }],
    ["CSS 注入颜色", { primaryColor: "#FFF; } * { display: none" }],
    ["注入字体", { fontFamily: 'serif; } * { color: red' }],
    ["越界字号", { fontSize: 99 }],
  ])("恶意/非法 theme 值回落默认（%s）", (_name, theme) => {
    const html = renderWechatHtml(SAMPLE, theme);
    expect(html).toMatch(/<a[^>]*style="color:#00E676/);
    expect(html).not.toContain("display: none");
  });
});
