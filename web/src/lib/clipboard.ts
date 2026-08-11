const UNSUPPORTED_MESSAGE = "富文本复制需要 HTTPS 和现代浏览器剪贴板权限"
const PLAIN_TEXT_UNSUPPORTED_MESSAGE = "复制 Markdown 需要 HTTPS 和浏览器剪贴板权限"

export async function copyPlainText(text: string): Promise<void> {
  if (!window.isSecureContext || !navigator.clipboard?.writeText) {
    throw new Error(PLAIN_TEXT_UNSUPPORTED_MESSAGE)
  }
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    throw new Error(`${PLAIN_TEXT_UNSUPPORTED_MESSAGE}，请检查浏览器权限`)
  }
}

export async function copyRichHtml(html: string, plainText: string): Promise<void> {
  if (!window.isSecureContext || !navigator.clipboard?.write || typeof ClipboardItem === "undefined") {
    throw new Error(UNSUPPORTED_MESSAGE)
  }
  const item = new ClipboardItem({
    "text/html": new Blob([html], { type: "text/html" }),
    "text/plain": new Blob([plainText], { type: "text/plain" }),
  })
  try {
    await navigator.clipboard.write([item])
  } catch {
    throw new Error(`${UNSUPPORTED_MESSAGE}，请检查浏览器权限`)
  }
}
