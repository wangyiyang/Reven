import { initRenderer } from "@md/core/renderer";
import { modifyHtmlContent } from "@md/core/utils";
import { baseCSSContent, themeMap } from "@md/shared/configs/theme";
import juice from "juice";
import sanitizeHtml from "sanitize-html";

const renderer = initRenderer({
  citeStatus: true,
  countStatus: false,
  isMacCodeBlock: true,
  isShowLineNumber: false,
  legend: "alt-title",
  themeMode: "light",
});

const cssVariables = `
:root {
  --md-primary-color: #0F4C81;
  --md-font-family: -apple-system-font, BlinkMacSystemFont, "PingFang SC", sans-serif;
  --md-font-size: 16px;
  --foreground: 0 0% 20%;
}`;

const wechatBaseCSS = `
section { font-family: var(--md-font-family); font-size: var(--md-font-size); line-height: 1.75; }
h1 { padding: 0 1em; border-bottom: 2px solid var(--md-primary-color); font-weight: bold; }
`;

const sanitizeOptions: sanitizeHtml.IOptions = {
  allowedTags: sanitizeHtml.defaults.allowedTags.concat(["img", "figure", "figcaption"]),
  allowedAttributes: {
    "*": ["class", "style", "data-*"],
    a: ["href", "title"],
    img: ["src", "alt", "title"],
  },
  allowedSchemes: ["http", "https", "mailto", "tel", "reven-asset"],
  allowProtocolRelative: false,
  disallowedTagsMode: "discard",
};

export function renderWechatHtml(markdown: string): string {
  const placeholders = new Map<string, string>();
  const protectedMarkdown = markdown.replace(
    /reven-asset:\/\/[A-Za-z0-9/_-]+/g,
    (source) => {
      const token = `https://reven.invalid/assets/${placeholders.size}`;
      placeholders.set(token, source);
      return token;
    },
  );
  renderer.reset({});
  const rendered = modifyHtmlContent(protectedMarkdown, renderer);
  const css = `${cssVariables}\n${baseCSSContent}\n${themeMap.default}\n${wechatBaseCSS}`;
  const styled = juice.inlineContent(rendered, css, {
    applyStyleTags: true,
    removeStyleTags: true,
    preserveMediaQueries: false,
    resolveCSSVariables: true,
  });
  const safeHtml = sanitizeHtml(styled, sanitizeOptions);
  return [...placeholders].reduce(
    (html, [token, source]) => html.replaceAll(token, source),
    safeHtml,
  );
}
