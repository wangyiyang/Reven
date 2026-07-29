import { initRenderer } from "@md/core/renderer";
import { modifyHtmlContent } from "@md/core/utils";
import { baseCSSContent, themeMap } from "@md/shared/configs/theme";
import juice from "juice";
import sanitizeHtml from "sanitize-html";

import { sanitizeInlineStyle } from "./css-sanitizer";

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

const assetPattern = /^reven-asset:\/\/image\/[1-9][0-9]*$/;
const protectedAssetPattern = /^https:\/\/reven\.invalid\/assets\/([A-Za-z0-9_-]+)$/;

function protectAssetSources(markdown: string): string {
  return markdown.replace(/reven-asset:\/\/image\/[1-9][0-9]*/g, (source) => {
    const encoded = Buffer.from(source).toString("base64url");
    return `https://reven.invalid/assets/${encoded}`;
  });
}

function restoreAssetSource(source: string): string {
  const match = protectedAssetPattern.exec(source);
  if (!match) {
    return source;
  }
  try {
    const decoded = Buffer.from(match[1], "base64url").toString("utf8");
    return assetPattern.test(decoded) ? decoded : source;
  } catch {
    return source;
  }
}

function transformTag(tagName: string, attributes: sanitizeHtml.Attributes) {
  const transformed = { ...attributes };
  const style = transformed.style ? sanitizeInlineStyle(transformed.style) : undefined;
  if (style) {
    transformed.style = style;
  } else {
    delete transformed.style;
  }
  if (tagName === "img" && transformed.src) {
    transformed.src = restoreAssetSource(transformed.src);
  }
  return { tagName, attribs: transformed };
}

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
  transformTags: {
    "*": transformTag,
  },
};

export function renderWechatHtml(markdown: string): string {
  const protectedMarkdown = protectAssetSources(markdown);
  renderer.reset({});
  const rendered = modifyHtmlContent(protectedMarkdown, renderer);
  const css = `${cssVariables}\n${baseCSSContent}\n${themeMap.default}\n${wechatBaseCSS}`;
  const styled = juice.inlineContent(rendered, css, {
    applyStyleTags: true,
    removeStyleTags: true,
    preserveMediaQueries: false,
    resolveCSSVariables: true,
  });
  return sanitizeHtml(styled, sanitizeOptions);
}
