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

export interface WechatTheme {
  primaryColor?: string;
  fontFamily?: string;
  fontSize?: number;
}

const DEFAULT_THEME = {
  primaryColor: "#00E676",
  fontFamily:
    '"Inter", "Noto Sans SC", "Source Han Sans SC", -apple-system-font, BlinkMacSystemFont, "PingFang SC", sans-serif',
  fontSize: 16,
} as const;

const COLOR_PATTERN = /^#[0-9A-Fa-f]{6}$/;
const FONT_FORBIDDEN = /[{};<>\\\n\r]/;

function sanitizeTheme(theme?: WechatTheme): { primaryColor: string; fontFamily: string; fontSize: number } {
  const primaryColor =
    theme?.primaryColor && COLOR_PATTERN.test(theme.primaryColor) ? theme.primaryColor : DEFAULT_THEME.primaryColor;
  const fontFamily =
    theme?.fontFamily && theme.fontFamily.length <= 200 && !FONT_FORBIDDEN.test(theme.fontFamily)
      ? theme.fontFamily
      : DEFAULT_THEME.fontFamily;
  const fontSize =
    theme?.fontSize && Number.isInteger(theme.fontSize) && theme.fontSize >= 12 && theme.fontSize <= 24
      ? theme.fontSize
      : DEFAULT_THEME.fontSize;
  return { primaryColor, fontFamily, fontSize };
}

function buildCssVariables(theme: { primaryColor: string; fontFamily: string; fontSize: number }): string {
  return `
:root {
  --md-primary-color: ${theme.primaryColor};
  --md-font-family: ${theme.fontFamily};
  --md-font-size: ${theme.fontSize}px;
  --foreground: 0 0% 4%;
}`;
}

function buildWechatBaseCSS(theme: { primaryColor: string; fontFamily: string; fontSize: number }): string {
  return `
section { font-family: var(--md-font-family); font-size: var(--md-font-size); line-height: 1.75; }
h1 { padding: 0 1em; border-bottom: 2px solid #0A0A0A; font-weight: bold; color: #0A0A0A; }
h2 { color: #0A0A0A; background: none; }
h3 { border-left: 3px solid #0A0A0A; color: #0A0A0A; }
h4, h5, h6 { color: #0A0A0A; }
a { color: ${theme.primaryColor}; font-weight: 600; text-decoration: none; }
blockquote { font-style: italic; border-left: 4px solid ${theme.primaryColor}; border-radius: 0; background: rgb(10 10 10 / 0.05); color: #0A0A0A; }
blockquote > p { color: rgb(10 10 10 / 0.72); }
img { border: 1px solid #E5E5E5; border-radius: 0; }
.codespan { color: #0A0A0A; background: rgb(10 10 10 / 0.06); border: 1px solid #E5E5E5; font-family: "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
pre.code__pre, .hljs.code__pre { background: #0A0A0A; }
pre.code__pre > code, .hljs.code__pre > code { color: #FAFAFA; font-family: "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
pre.code__pre .hljs-keyword, pre.code__pre .hljs-selector-tag, pre.code__pre .hljs-built_in, pre.code__pre .hljs-literal { color: ${theme.primaryColor}; }
pre.code__pre .hljs-comment, pre.code__pre .hljs-quote { color: rgb(250 250 250 / 0.45); }
pre.code__pre .hljs-string, pre.code__pre .hljs-attr, pre.code__pre .hljs-attribute, pre.code__pre .hljs-number, pre.code__pre .hljs-symbol, pre.code__pre .hljs-title, pre.code__pre .hljs-name { color: #FAFAFA; }
`;
}

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

export function renderWechatHtml(markdown: string, theme?: WechatTheme): string {
  const resolvedTheme = sanitizeTheme(theme);
  const protectedAssets = protectAssetSources(markdown);
  renderer.reset({});
  const rendered = modifyHtmlContent(protectedAssets.markdown, renderer);
  const css = `${buildCssVariables(resolvedTheme)}\n${baseCSSContent}\n${themeMap.default}\n${buildWechatBaseCSS(resolvedTheme)}`;
  const styled = juice.inlineContent(rendered, css, {
    applyStyleTags: true,
    removeStyleTags: true,
    preserveMediaQueries: false,
    resolveCSSVariables: true,
  });
  return sanitizeHtml(styled, createSanitizeOptions(protectedAssets.assets));
}
