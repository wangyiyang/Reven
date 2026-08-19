import { useMutation, useQueryClient } from "@tanstack/react-query"
import * as Dialog from "@radix-ui/react-dialog"
import { Copy, LoaderCircle } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { apiRequest } from "@/lib/api"
import { copyPlainText } from "@/lib/clipboard"
import { parsePortableMarkdown } from "./response-parsers"

export function PortableMarkdownCopy(props: { articleId: string; enabled: boolean }) {
  const [manualMarkdown, setManualMarkdown] = useState<string | null>(null)
  const queryClient = useQueryClient()
  const copy = useMutation({
    mutationFn: async () =>
      parsePortableMarkdown(
        await apiRequest<unknown>(`/articles/${props.articleId}/portable-markdown`, { method: "POST" }),
      ),
    onSuccess: async ({ markdown }) => {
      try {
        await copyPlainText(markdown)
        toast.success("已复制")
      } catch (error) {
        setManualMarkdown(markdown)
        toast.error(error instanceof Error ? error.message : "复制 Markdown 失败")
      }
    },
    onError: async (error: Error) => {
      toast.error(error.message)
      await queryClient.invalidateQueries({ queryKey: ["article", props.articleId] })
    },
  })

  return (
    <>
      <Button
        disabled={copy.isPending || !props.enabled}
        onClick={() => copy.mutate()}
        title={props.enabled ? undefined : "请先完成最新内容同步"}
        type="button"
        variant="outline"
      >
        {copy.isPending
          ? <LoaderCircle aria-hidden className="animate-spin" size={15} />
          : <Copy aria-hidden size={15} />}
        复制 Markdown
      </Button>
      <ManualCopyDialog markdown={manualMarkdown} onClose={() => setManualMarkdown(null)} />
    </>
  )
}

function ManualCopyDialog(props: { markdown: string | null; onClose: () => void }) {
  return (
    <Dialog.Root onOpenChange={(open) => !open && props.onClose()} open={props.markdown !== null}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/55" />
        <Dialog.Content className="fixed top-1/2 left-1/2 z-50 w-[calc(100%-2rem)] max-w-3xl -translate-x-1/2 -translate-y-1/2 rounded-lg border border-[var(--line)] bg-[var(--bg)] p-6 shadow-lg">
          <Dialog.Title className="text-lg font-semibold">手动复制 Markdown</Dialog.Title>
          <Dialog.Description className="mt-2 text-sm text-[var(--muted)]">
            浏览器未授予剪贴板权限。请在下方选中全部内容后手动复制。
          </Dialog.Description>
          <Textarea
            aria-label="可移植 Markdown 内容"
            className="mt-4 min-h-80 resize-y font-mono text-xs"
            onFocus={(event) => event.currentTarget.select()}
            readOnly
            value={props.markdown ?? ""}
          />
          <div className="mt-4 flex justify-end">
            <Dialog.Close asChild><Button variant="outline">关闭</Button></Dialog.Close>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
