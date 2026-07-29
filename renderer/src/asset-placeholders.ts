import { createHash } from "node:crypto";

const assetSourcePattern = /reven-asset:\/\/image\/[1-9][0-9]*/g;
const protectedTokenPattern = /https:\/\/reven\.invalid\/assets\/[A-Za-z0-9_-]+\/(?:0|[1-9][0-9]*)/g;
const maxAssetCount = 5000;
const maxSaltAttempts = 1024;

export type NonceDeriver = (markdown: string, salt: number) => string;

export interface ProtectedAssets {
  markdown: string;
  assets: Map<string, string>;
}

function deriveNonce(markdown: string, salt: number): string {
  return createHash("sha256")
    .update("reven-wechat-assets\0")
    .update(String(salt))
    .update("\0")
    .update(markdown)
    .digest("hex");
}

function collectAssets(markdown: string): string[] {
  return [...new Set(markdown.match(assetSourcePattern) ?? [])];
}

function collectExistingTokens(markdown: string): Set<string> {
  return new Set(markdown.match(protectedTokenPattern) ?? []);
}

function createTokenMap(
  existingTokens: ReadonlySet<string>,
  assets: string[],
  nonce: string,
): Map<string, string> | undefined {
  const tokens = assets.map((_asset, index) => `https://reven.invalid/assets/${nonce}/${index}`);
  if (tokens.some((token) => existingTokens.has(token))) {
    return undefined;
  }
  return new Map(tokens.map((token, index) => [token, assets[index]]));
}

export function protectAssetSources(
  markdown: string,
  nonceDeriver: NonceDeriver = deriveNonce,
): ProtectedAssets {
  const uniqueAssets = collectAssets(markdown);
  if (uniqueAssets.length === 0) {
    return { markdown, assets: new Map() };
  }
  if (uniqueAssets.length > maxAssetCount) {
    throw new Error("asset_placeholder_limit");
  }
  const existingTokens = collectExistingTokens(markdown);
  for (let salt = 0; salt < maxSaltAttempts; salt += 1) {
    const assets = createTokenMap(existingTokens, uniqueAssets, nonceDeriver(markdown, salt));
    if (!assets) {
      continue;
    }
    const tokensByAsset = new Map([...assets].map(([token, asset]) => [asset, token]));
    const protectedMarkdown = markdown.replace(assetSourcePattern, (asset) => tokensByAsset.get(asset) ?? asset);
    return { markdown: protectedMarkdown, assets };
  }
  throw new Error("asset_placeholder_collision");
}
