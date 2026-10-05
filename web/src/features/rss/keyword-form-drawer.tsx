import { useEffect, useState, type FormEvent } from "react"

import { Button } from "@/components/ui/button"
import { Drawer } from "@/components/ui/drawer"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"

import type { RssKeywordInput } from "./rss-api"
import type { RssKeyword, RssKeywordKind } from "./types"

type KeywordFormDrawerProps = {
  open: boolean
  busy: boolean
  editing: RssKeyword | null
  onClose: () => void
  onSubmit: (input: RssKeywordInput) => Promise<boolean>
}

export function KeywordFormDrawer(props: KeywordFormDrawerProps) {
  return (
    <Drawer onClose={props.onClose} open={props.open} title={props.editing ? "编辑关键词" : "新建关键词"}>
      <KeywordForm busy={props.busy} editing={props.editing} onClose={props.onClose} onSubmit={props.onSubmit} />
    </Drawer>
  )
}

// 表单状态挂在 Drawer children 内：关闭（含退出动画结束）后由 Radix 卸载，
// 下次打开重新挂载，表单自然回到初始值
function KeywordForm({ busy, editing, onClose, onSubmit }: Omit<KeywordFormDrawerProps, "open">) {
  const [term, setTerm] = useState("")
  const [kind, setKind] = useState<RssKeywordKind>("positive")
  useEffect(() => {
    setTerm(editing?.term ?? "")
    setKind(editing?.kind ?? "positive")
  }, [editing])
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const saved = await onSubmit({ term: term.trim(), kind, enabled: editing?.enabled ?? true })
    if (saved) setTerm("")
  }
  return (
    <form className="space-y-4" onSubmit={submit}>
      <div className="space-y-2">
        <Label htmlFor="rss-keyword-term">关键词</Label>
        <Input id="rss-keyword-term" maxLength={200} onChange={(event) => setTerm(event.target.value)} required value={term} />
      </div>
      <div className="space-y-2">
        <Label htmlFor="rss-keyword-kind">关键词类型</Label>
        <select
          className="h-10 w-full rounded-md border border-[var(--line)] bg-[var(--bg)] px-3 text-sm outline-none focus:border-[var(--signal)]"
          id="rss-keyword-kind"
          onChange={(event) => setKind(event.target.value === "negative" ? "negative" : "positive")}
          value={kind}
        >
          <option value="positive">正向关键词</option>
          <option value="negative">反向关键词</option>
        </select>
      </div>
      <div className="flex justify-end gap-3 pt-2">
        <Button onClick={onClose} type="button" variant="outline">取消</Button>
        <Button disabled={busy} type="submit">{editing ? "保存关键词" : "添加关键词"}</Button>
      </div>
    </form>
  )
}
