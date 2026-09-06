import { renderWechatHtml, type WechatTheme } from "./render";

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

function parseInput(raw: string): { markdown: string; theme?: WechatTheme } {
  const input: unknown = JSON.parse(raw);
  if (!input || Array.isArray(input) || typeof input !== "object") {
    fail();
  }
  const markdown = (input as Record<string, unknown>).markdown;
  if (typeof markdown !== "string") {
    fail();
  }
  const theme = parseTheme((input as Record<string, unknown>).theme);
  return theme ? { markdown, theme } : { markdown };
}

function parseTheme(raw: unknown): WechatTheme | undefined {
  if (!raw || Array.isArray(raw) || typeof raw !== "object") {
    return undefined;
  }
  const record = raw as Record<string, unknown>;
  const theme: WechatTheme = {};
  if (typeof record.primaryColor === "string") {
    theme.primaryColor = record.primaryColor;
  }
  if (typeof record.fontFamily === "string") {
    theme.fontFamily = record.fontFamily;
  }
  if (typeof record.fontSize === "number") {
    theme.fontSize = record.fontSize;
  }
  return Object.keys(theme).length > 0 ? theme : undefined;
}

async function main(): Promise<void> {
  try {
    const { markdown, theme } = parseInput(await readInput());
    const html = renderWechatHtml(markdown, theme);
    process.stdout.write(`${JSON.stringify({ ok: true, html })}\n`);
  } catch {
    fail();
  }
}

void main();
