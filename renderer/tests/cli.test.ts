import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

import { expect, test } from "vitest";

const cliPath = fileURLToPath(new URL("../dist/cli.mjs", import.meta.url));

function runCli(input: string): Promise<{ code: number | null; stdout: string; stderr: string }> {
  return new Promise((resolve) => {
    const child = spawn(process.execPath, [cliPath], {
      stdio: ["pipe", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    child.stdout.setEncoding("utf8").on("data", (chunk: string) => (stdout += chunk));
    child.stderr.setEncoding("utf8").on("data", (chunk: string) => (stderr += chunk));
    child.on("close", (code) => resolve({ code, stdout, stderr }));
    child.stdin.on("error", () => undefined);
    child.stdin.end(input);
  });
}

test("CLI returns only a successful JSON object", async () => {
  const result = await runCli(JSON.stringify({ markdown: "# 标题" }));

  expect(result.code).toBe(0);
  expect(JSON.parse(result.stdout)).toMatchObject({ ok: true });
  expect(result.stderr).toBe("");
});

test.each(["", "{", "[]", JSON.stringify({ markdown: 1 })])(
  "CLI returns a generic failure for invalid input",
  async (input) => {
    const result = await runCli(input);

    expect(result.code).toBe(1);
    expect(result.stdout).toBe('{"ok":false,"error":"render_failed"}\n');
    expect(result.stderr).toBe("");
  },
);

test("CLI rejects input larger than one MiB", async () => {
  const result = await runCli(JSON.stringify({ markdown: "x".repeat(1024 * 1024) }));

  expect(result.code).toBe(1);
  expect(result.stdout).toBe('{"ok":false,"error":"render_failed"}\n');
});
