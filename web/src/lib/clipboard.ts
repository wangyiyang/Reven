const UNSUPPORTED_MESSAGE = "富文本复制需要 HTTPS 和现代浏览器剪贴板权限"

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
