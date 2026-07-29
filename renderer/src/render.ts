import { initRenderer } from "@md/core/renderer";
import { modifyHtmlContent } from "@md/core/utils";
import { baseCSSContent, themeMap } from "@md/shared/configs/theme";
import juice from "juice";
import sanitizeHtml from "sanitize-html";

import { protectAssetSources } from "./asset-placeholders";
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

function transformTag(
  tagName: string,
  attributes: sanitizeHtml.Attributes,
  assets: ReadonlyMap<string, string>,
) {
  const transformed = { ...attributes };
  const style = transformed.style ? sanitizeInlineStyle(transformed.style) : undefined;
  if (style) {
    transformed.style = style;
  } else {
    delete transformed.style;
  }
  if (tagName === "img" && transformed.src) {
    transformed.src = assets.get(transformed.src) ?? transformed.src;
  }
  return { tagName, attribs: transformed };
}

function createSanitizeOptions(assets: ReadonlyMap<string, string>): sanitizeHtml.IOptions {
  return {
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
      "*": (tagName, attributes) => transformTag(tagName, attributes, assets),
    },
  };
}

export function renderWechatHtml(markdown: string): string {
  const protectedAssets = protectAssetSources(markdown);
  renderer.reset({});
  const rendered = modifyHtmlContent(protectedAssets.markdown, renderer);
  const css = `${cssVariables}\n${baseCSSContent}\n${themeMap.default}\n${wechatBaseCSS}`;
  const styled = juice.inlineContent(rendered, css, {
    applyStyleTags: true,
    removeStyleTags: true,
    preserveMediaQueries: false,
    resolveCSSVariables: true,
  });
  return sanitizeHtml(styled, createSanitizeOptions(protectedAssets.assets));
}
