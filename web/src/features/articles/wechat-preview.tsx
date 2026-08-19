import { useMutation } from "@tanstack/react-query"
import * as Dialog from "@radix-ui/react-dialog"
import { Copy, Eye, LoaderCircle } from "lucide-react"
import { useRef, useState } from "react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { apiRequest } from "@/lib/api"
import { copyRichHtml } from "@/lib/clipboard"
import { parsePreview } from "./response-parsers"

export function WechatPreview({ articleId, title, enabled }: { articleId: string; title: string; enabled: boolean }) {
  const [open, setOpen] = useState(false)
  const lock = useRef(false)
  const preview = useMutation({
    mutationFn: async () => parsePreview(await apiRequest<unknown>(`/articles/${articleId}/preview/wechat`, { method: "POST" })),
    onSuccess: () => setOpen(true),
    onError: (error: Error) => toast.error(error.message),
    onSettled: () => { lock.current = false },
  })
  const runPreview = () => {
    if (lock.current) return
    lock.current = true
    preview.mutate()
  }
  const copy = async () => {
    if (!preview.data) return
    try {
      await copyRichHtml(preview.data.html, toPlainText(title, preview.data.html))
      toast.success("已复制微信富文本")
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "富文本复制失败")
    }
  }
  return (
    <>
      <Button disabled={preview.isPending || !enabled} onClick={runPreview} title={enabled ? undefined : "请先完成最新内容同步"} type="button" variant="outline">
        {preview.isPending ? <LoaderCircle aria-hidden className="animate-spin" size={15} /> : <Eye aria-hidden size={15} />}
        生成微信预览
      </Button>
      <PreviewDialog html={preview.data?.html} onCopy={copy} onOpenChange={setOpen} open={open} title={title} />
    </>
  )
}

function PreviewDialog(props: {
  html: string | undefined
  onCopy: () => void
  onOpenChange: (open: boolean) => void
  open: boolean
  title: string
}) {
  return (
    <Dialog.Root onOpenChange={props.onOpenChange} open={props.open}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/55" />
        <Dialog.Content className="fixed top-1/2 left-1/2 z-50 max-h-[92vh] w-[calc(100%-2rem)] max-w-4xl -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-lg border border-[var(--line)] bg-[var(--bg)] p-6 shadow-lg">
          <Dialog.Title className="text-lg font-semibold">微信富文本预览</Dialog.Title>
          <Dialog.Description className="mt-2 text-sm text-[var(--muted)]">使用最近一次有效内容快照，不重新读取 Notion 正文、不上传素材、不创建草稿。</Dialog.Description>
          <div className="mt-4 flex justify-end gap-2">
            <Dialog.Close asChild><Button size="sm" variant="ghost">关闭</Button></Dialog.Close>
            <Button onClick={props.onCopy} size="sm"><Copy aria-hidden size={14} />复制富文本</Button>
          </div>
          {props.html && (
            <iframe
              className="mt-4 h-[65vh] w-full border border-[var(--line)] bg-white"
              sandbox=""
              srcDoc={props.html}
              title={`${props.title}的微信预览`}
            />
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}

function toPlainText(title: string, html: string) {
  const document = new DOMParser().parseFromString(html, "text/html")
  return `${title}\n\n${document.body.textContent?.trim() ?? ""}`
}
