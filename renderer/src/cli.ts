import { renderWechatHtml } from "./render";

const MAX_INPUT_BYTES = 1024 * 1024;
const failure = JSON.stringify({ ok: false, error: "render_failed" });

function fail(): never {
  process.stdout.write(`${failure}\n`);
  process.exit(1);
}

async function readInput(): Promise<string> {
  const chunks: Buffer[] = [];
  let size = 0;
  for await (const chunk of process.stdin) {
    const buffer = Buffer.from(chunk);
    size += buffer.length;
    if (size > MAX_INPUT_BYTES) {
      fail();
    }
    chunks.push(buffer);
  }
  return Buffer.concat(chunks).toString("utf8");
}

function parseMarkdown(raw: string): string {
  const input: unknown = JSON.parse(raw);
  if (!input || Array.isArray(input) || typeof input !== "object") {
    fail();
  }
  const markdown = (input as Record<string, unknown>).markdown;
  if (typeof markdown !== "string") {
    fail();
  }
  return markdown;
}

async function main(): Promise<void> {
  try {
    const markdown = parseMarkdown(await readInput());
    const html = renderWechatHtml(markdown);
    process.stdout.write(`${JSON.stringify({ ok: true, html })}\n`);
  } catch {
    fail();
  }
}

void main();
