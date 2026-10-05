import { useEffect, useState, type FormEvent } from "react"

import { Button } from "@/components/ui/button"
import { Drawer } from "@/components/ui/drawer"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"

import type { RssSourceInput } from "./rss-api"
import type { RssSource } from "./types"

type SourceFormDrawerProps = {
  open: boolean
  busy: boolean
  editing: RssSource | null
  onClose: () => void
  onSubmit: (input: RssSourceInput) => Promise<boolean>
}

export function SourceFormDrawer(props: SourceFormDrawerProps) {
  return (
    <Drawer onClose={props.onClose} open={props.open} title={props.editing ? "编辑 RSS 源" : "新建 RSS 源"}>
      <SourceForm busy={props.busy} editing={props.editing} onClose={props.onClose} onSubmit={props.onSubmit} />
    </Drawer>
  )
}

// 表单状态挂在 Drawer children 内：关闭（含退出动画结束）后由 Radix 卸载，
// 下次打开重新挂载，表单自然回到初始值
function SourceForm({ busy, editing, onClose, onSubmit }: Omit<SourceFormDrawerProps, "open">) {
  const [name, setName] = useState("")
  const [feedUrl, setFeedUrl] = useState("")
  useEffect(() => {
    setName(editing?.name ?? "")
    setFeedUrl(editing?.feed_url ?? "")
  }, [editing])
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const saved = await onSubmit({
      name: name.trim(),
      feed_url: feedUrl.trim(),
      enabled: editing?.enabled ?? true,
    })
    if (saved) {
      setName("")
      setFeedUrl("")
    }
  }
  return (
    <form className="space-y-4" onSubmit={submit}>
      <div className="space-y-2">
        <Label htmlFor="rss-source-name">RSS 源名称</Label>
        <Input id="rss-source-name" maxLength={200} onChange={(event) => setName(event.target.value)} required value={name} />
      </div>
      <div className="space-y-2">
        <Label htmlFor="rss-feed-url">Feed URL</Label>
        <Input id="rss-feed-url" onChange={(event) => setFeedUrl(event.target.value)} required type="url" value={feedUrl} />
      </div>
      <div className="flex justify-end gap-3 pt-2">
        <Button onClick={onClose} type="button" variant="outline">取消</Button>
        <Button disabled={busy} type="submit">{editing ? "保存 RSS 源" : "添加 RSS 源"}</Button>
      </div>
    </form>
  )
}
