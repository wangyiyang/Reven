import { useMutation } from "@tanstack/react-query"
import * as Dialog from "@radix-ui/react-dialog"
import { Copy, Eye, LoaderCircle } from "lucide-react"
import { useRef, useState } from "react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { apiRequest } from "@/lib/api"
import { copyRichHtml } from "@/lib/clipboard"

export function WechatPreview({ articleId, title }: { articleId: string; title: string }) {
  const [open, setOpen] = useState(false)
  const lock = useRef(false)
  const preview = useMutation({
    mutationFn: async () => {
      if (lock.current) return
      lock.current = true
      try {
        return await apiRequest<{ html: string }>(`/articles/${articleId}/preview/wechat`, { method: "POST" })
      } finally {
        lock.current = false
      }
    },
    onSuccess: () => setOpen(true),
    onError: (error: Error) => toast.error(error.message),
  })
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
      <Button disabled={preview.isPending} onClick={() => preview.mutate()} type="button" variant="outline">
        {preview.isPending ? <LoaderCircle aria-hidden className="animate-spin" size={15} /> : <Eye aria-hidden size={15} />}
        生成微信预览
      </Button>
      <Dialog.Root onOpenChange={setOpen} open={open}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-50 bg-black/55" />
          <Dialog.Content className="fixed top-1/2 left-1/2 z-50 max-h-[92vh] w-[calc(100%-2rem)] max-w-4xl -translate-x-1/2 -translate-y-1/2 overflow-y-auto border border-[var(--ink)] bg-[var(--paper)] p-6 shadow-[10px_10px_0_var(--ink)]">
            <Dialog.Title className="font-display text-3xl">微信富文本预览</Dialog.Title>
            <Dialog.Description className="mt-2 text-sm text-[var(--muted)]">临时读取最新 Notion 内容，不上传素材、不创建草稿、不修改稿件状态。</Dialog.Description>
            <div className="mt-4 flex justify-end gap-2">
              <Dialog.Close asChild><Button size="sm" variant="ghost">关闭</Button></Dialog.Close>
              <Button onClick={copy} size="sm"><Copy aria-hidden size={14} />复制富文本</Button>
            </div>
            {preview.data && (
              <iframe
                className="mt-4 h-[65vh] w-full border border-[var(--line)] bg-white"
                sandbox=""
                srcDoc={preview.data.html}
                title={`${title}的微信预览`}
              />
            )}
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </>
  )
}

function toPlainText(title: string, html: string) {
  const document = new DOMParser().parseFromString(html, "text/html")
  return `${title}\n\n${document.body.textContent?.trim() ?? ""}`
}
