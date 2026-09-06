import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Upload } from "lucide-react"
import { useRef, useState } from "react"
import { toast } from "sonner"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { fetchBrandAssets, updateBrandAsset, uploadBrandAsset } from "./brand-api"
import { ASSET_PURPOSES, type BrandAsset } from "./types"

export function AssetsSection() {
  const client = useQueryClient()
  const assets = useQuery({ queryKey: ["brand-assets"], queryFn: fetchBrandAssets })
  const fileRef = useRef<HTMLInputElement>(null)
  const [label, setLabel] = useState("")
  const [purpose, setPurpose] = useState<string>("其他")

  const invalidate = async () => {
    await client.invalidateQueries({ queryKey: ["brand-assets"] })
  }
  const upload = useMutation({
    mutationFn: async () => {
      const file = fileRef.current?.files?.[0]
      if (!file) throw new Error("请选择图片文件")
      if (!label.trim()) throw new Error("请填写素材名称")
      await uploadBrandAsset(file, label.trim(), purpose)
    },
    onSuccess: async () => {
      toast.success("素材已上传")
      setLabel("")
      if (fileRef.current) fileRef.current.value = ""
      await invalidate()
    },
    onError: (error: Error) => toast.error(error.message),
  })
  const patch = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) => updateBrandAsset(id, { enabled }),
    onSuccess: invalidate,
    onError: (error: Error) => toast.error(error.message),
  })

  return (
    <Card>
      <CardHeader>
        <h2 className="text-base font-semibold">品牌素材库</h2>
        <p className="mt-1 text-xs text-[var(--muted)]">统一归档标志、二维码与封面等素材，供渠道模板与稿件封面选择引用。</p>
      </CardHeader>
      <CardContent>
        <div className="flex flex-wrap items-end gap-3 border-b border-[var(--line)] pb-5">
          <div>
            <Label className="mb-1.5 block text-xs text-[var(--muted)]">图片文件（PNG/JPEG/GIF/WebP，≤10MB）</Label>
            <input
              accept="image/png,image/jpeg,image/gif,image/webp"
              aria-label="素材文件"
              className="block w-full text-sm file:mr-3 file:border file:border-[var(--line)] file:bg-transparent file:px-3 file:py-1.5 file:text-xs"
              ref={fileRef}
              type="file"
            />
          </div>
          <div>
            <Label className="mb-1.5 block text-xs text-[var(--muted)]">素材名称</Label>
            <Input aria-label="素材名称" maxLength={200} onChange={(event) => setLabel(event.target.value)} value={label} />
          </div>
          <div>
            <Label className="mb-1.5 block text-xs text-[var(--muted)]">用途</Label>
            <Select onValueChange={setPurpose} value={purpose}>
              <SelectTrigger aria-label="素材用途" className="w-28"><SelectValue /></SelectTrigger>
              <SelectContent>
                {ASSET_PURPOSES.map((item) => <SelectItem key={item} value={item}>{item}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <Button disabled={upload.isPending} onClick={() => upload.mutate()} size="sm"><Upload aria-hidden size={13} />上传</Button>
        </div>
        {assets.isError && <p className="py-4 text-sm text-[var(--danger)]" role="alert">素材列表读取失败：{assets.error.message}</p>}
        {assets.isSuccess && assets.data.length === 0 && <p className="py-6 text-sm text-[var(--muted)]">还没有素材，先上传一个。</p>}
        {assets.isSuccess && assets.data.length > 0 && (
          <ul className="grid gap-3 pt-5 sm:grid-cols-2 lg:grid-cols-3">
            {assets.data.map((asset) => (
              <AssetCard asset={asset} busy={patch.isPending} key={asset.id} onToggle={(enabled) => patch.mutate({ id: asset.id, enabled })} />
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}

function AssetCard({ asset, busy, onToggle }: { asset: BrandAsset; busy: boolean; onToggle: (enabled: boolean) => void }) {
  return (
    <li className="flex gap-3 border border-[var(--line)] p-3">
      <img alt={asset.label} className="h-14 w-14 shrink-0 border border-[var(--line)] object-contain" src={asset.public_url} />
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-semibold">{asset.label}</p>
        <p className="mt-0.5 text-xs text-[var(--muted)]">
          {asset.width && asset.height ? `${asset.width}×${asset.height} · ` : ""}{(asset.byte_size / 1024).toFixed(0)}KB · {asset.source}
        </p>
        <div className="mt-2 flex items-center gap-2">
          <Badge className="text-xs">{asset.purpose}</Badge>
          <Button disabled={busy} onClick={() => onToggle(!asset.enabled)} size="sm" variant={asset.enabled ? "ghost" : "outline"}>
            {asset.enabled ? "停用" : "启用"}
          </Button>
        </div>
      </div>
    </li>
  )
}
