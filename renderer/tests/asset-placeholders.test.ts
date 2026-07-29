import { expect, test, vi } from "vitest";

import { protectAssetSources } from "../src/asset-placeholders";

test("uses one deterministic token for each distinct asset", () => {
  const markdown = [
    "![一](reven-asset://image/1)",
    "![重复](reven-asset://image/1)",
    "![二](reven-asset://image/2)",
  ].join("\n");

  const first = protectAssetSources(markdown);
  const second = protectAssetSources(markdown);

  expect(first).toEqual(second);
  expect(first.assets.size).toBe(2);
  expect(first.markdown.match(/https:\/\/reven\.invalid\/assets\//g)).toHaveLength(3);
});

test("changes salt when a candidate token already occurs in source markdown", () => {
  const collision = "https://reven.invalid/assets/collision/0";
  const markdown = `${collision}\n![真实](reven-asset://image/1)`;
  const deriveNonce = vi.fn((_source: string, salt: number) => (salt === 0 ? "collision" : "safe"));

  const result = protectAssetSources(markdown, deriveNonce);

  expect(result.markdown).toContain(collision);
  expect(result.markdown).toContain("https://reven.invalid/assets/safe/0");
  expect(result.assets.has(collision)).toBe(false);
  expect(result.assets.get("https://reven.invalid/assets/safe/0")).toBe("reven-asset://image/1");
  expect(deriveNonce).toHaveBeenCalledTimes(2);
});

test("does not derive tokens when markdown has no assets", () => {
  const deriveNonce = vi.fn(() => "unused");
  const result = protectAssetSources("正文", deriveNonce);

  expect(result).toEqual({ markdown: "正文", assets: new Map() });
  expect(deriveNonce).not.toHaveBeenCalled();
});

test("handles a near-limit document with five thousand distinct assets", () => {
  const images = Array.from(
    { length: 5000 },
    (_value, index) => `![图](reven-asset://image/${index + 1})`,
  ).join("\n");
  const markdown = `${"正文".repeat(400000)}\n${images}`;

  const result = protectAssetSources(markdown);

  expect(result.assets.size).toBe(5000);
  expect(result.markdown).not.toContain("reven-asset://");
});

test("rejects more than five thousand distinct assets", () => {
  const markdown = Array.from(
    { length: 5001 },
    (_value, index) => `![图](reven-asset://image/${index + 1})`,
  ).join("\n");

  expect(() => protectAssetSources(markdown)).toThrow("asset_placeholder_limit");
});
