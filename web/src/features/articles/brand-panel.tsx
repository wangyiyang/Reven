import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import * as Dialog from "@radix-ui/react-dialog"
import { ImagePlus, X } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { apiRequest } from "@/lib/api"
import { fetchBrandAssets, fetchBrandProfile, fetchChannelTemplate } from "@/features/brand/brand-api"
import type { BrandAsset } from "@/features/brand/types"
import type { ArticleDetail, JobDetail } from "./types"

export function BrandPanel({ article, job }: { article: ArticleDetail; job: JobDetail | null }) {
  const client = useQueryClient()
  const profile = useQuery({ queryKey: ["brand-profile"], queryFn: fetchBrandProfile })
  const wechat = useQuery({ queryKey: ["brand-template", "wechat"], queryFn: () => fetchChannelTemplate("wechat") })
  const blog = useQuery({ queryKey: ["brand-template", "blog"], queryFn: () => fetchChannelTemplate("blog") })

  const regenerate = useMutation({
    mutationFn: () => apiRequest(`/articles/${article.id}/jobs`, { method: "POST" }),
    onSuccess: async () => {
      toast.success("已按当前品牌配置生成新任务")
      await client.invalidateQueries({ queryKey: ["article", article.id] })
    },
    onError: (error: Error) => toast.error(error.message),
  })

  const frozen = job?.brand ?? null
  const fingerprint = frozen?.version_fingerprint
  const currentBrandVersion = profile.data?.published?.version ?? null
  const wechatVersion = wechat.data?.published?.version ?? null
  const blogVersion = blog.data?.published?.version ?? null
  const brandDrift =
    currentBrandVersion !== null && fingerprint?.brand_version !== undefined && fingerprint.brand_version !== currentBrandVersion
  const templateDrift =
    (wechatVersion !== null && fingerprint?.wechat_template_version != null && fingerprint.wechat_template_version !== wechatVersion) ||
    (blogVersion !== null && fingerprint?.blog_template_version != null && fingerprint.blog_template_version !== blogVersion)
  const stale = frozen !== null && (brandDrift || templateDrift)

  return (
    <section className="mt-8 rounded-lg border border-[var(--line)] bg-[var(--faint)] p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-base font-semibold">品牌与模板</h2>
        <CoverPicker article={article} />
      </div>
      <dl className="mt-5 grid gap-5 text-sm sm:grid-cols-2 lg:grid-cols-4">
        <MetaItem label="任务品牌绑定" value={frozen ? `品牌 v${fingerprint?.brand_version ?? "?"}` : "legacy（未绑定品牌）"} />
        <MetaItem
          label="微信模板"
          value={frozen ? (fingerprint?.wechat_template_version ? `v${fingerprint.wechat_template_version}` : "未绑定") : "—"}
        />
        <MetaItem
          label="博客模板"
          value={frozen ? (fingerprint?.blog_template_version ? `v${fingerprint.blog_template_version}` : "未绑定") : "—"}
        />
        <MetaItem label="当前品牌版本" value={currentBrandVersion !== null ? `v${currentBrandVersion}` : "未发布"} />
      </dl>
      {stale && (
        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-l-2 border-[var(--muted)] bg-[var(--bg)] p-4">
          <p className="text-sm">
            {brandDrift ? `品牌配置已更新到 v${currentBrandVersion}` : "渠道模板已更新"}，预览与新生成的任务将使用新版本；已在跑的任务保持冻结配置不变。
          </p>
          <Button disabled={regenerate.isPending} onClick={() => regenerate.mutate()} size="sm" variant="outline">按当前品牌重新生成任务</Button>
        </div>
      )}
      {!frozen && job && <p className="mt-4 text-xs text-[var(--muted)]">该任务按 legacy 默认行为发布；配置并发布品牌档案后，新任务自动套用。</p>}
    </section>
  )
}

function CoverPicker({ article }: { article: ArticleDetail }) {
  const client = useQueryClient()
  const [open, setOpen] = useState(false)
  const assets = useQuery({ queryKey: ["brand-assets"], queryFn: fetchBrandAssets, enabled: open })
  const select = useMutation({
    mutationFn: (assetId: string | null) =>
      apiRequest(`/articles/${article.id}/cover`, { method: "POST", body: JSON.stringify({ asset_id: assetId }) }),
    onSuccess: async () => {
      toast.success("封面选择已更新")
      setOpen(false)
      await client.invalidateQueries({ queryKey: ["article", article.id] })
    },
    onError: (error: Error) => toast.error(error.message),
  })
  const candidates = (assets.data ?? []).filter(
    (asset) => asset.enabled && (asset.purpose === "封面" || asset.purpose === "其他"),
  )
  return (
    <Dialog.Root onOpenChange={setOpen} open={open}>
      <Dialog.Trigger asChild>
        <Button size="sm" variant="outline"><ImagePlus aria-hidden size={13} />选择品牌封面</Button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/55" />
        <Dialog.Content className="fixed top-1/2 left-1/2 z-50 w-[calc(100%-2rem)] max-w-2xl -translate-x-1/2 -translate-y-1/2 rounded-lg border border-[var(--line)] bg-[var(--bg)] p-6 shadow-lg">
          <div className="flex items-start justify-between gap-6">
            <div>
              <Dialog.Title className="text-lg font-semibold">选择品牌封面</Dialog.Title>
              <Dialog.Description className="mt-2 text-sm text-[var(--muted)]">
                选择的素材优先于 Notion 封面与模板默认封面；下次准备时生效。
                {article.selected_cover_asset_id && "当前已选择品牌素材封面。"}
              </Dialog.Description>
            </div>
            <Dialog.Close asChild>
              <Button aria-label="关闭封面选择" size="sm" variant="ghost"><X size={16} /></Button>
            </Dialog.Close>
          </div>
          {assets.isLoading && <p className="py-6 text-sm text-[var(--muted)]">正在读取素材库…</p>}
          {assets.isError && <p className="py-6 text-sm text-[var(--danger)]">素材读取失败：{assets.error.message}</p>}
          {assets.isSuccess && candidates.length === 0 && (
            <p className="py-6 text-sm text-[var(--muted)]">素材库中还没有可用的封面素材，请先在「品牌与发布」页上传。</p>
          )}
          {candidates.length > 0 && (
            <ul className="mt-5 grid max-h-80 gap-3 overflow-y-auto sm:grid-cols-3">
              {candidates.map((asset) => (
                <CoverOption
                  asset={asset}
                  busy={select.isPending}
                  key={asset.id}
                  onSelect={() => select.mutate(asset.id)}
                  selected={article.selected_cover_asset_id === asset.id}
                />
              ))}
            </ul>
          )}
          {article.selected_cover_asset_id && (
            <div className="mt-4 border-t border-[var(--line)] pt-4">
              <Button disabled={select.isPending} onClick={() => select.mutate(null)} size="sm" variant="ghost">清除选择，回落默认封面</Button>
            </div>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}

function CoverOption({ asset, selected, busy, onSelect }: { asset: BrandAsset; selected: boolean; busy: boolean; onSelect: () => void }) {
  return (
    <li>
      <button
        className={`w-full border p-2 text-left transition-colors ${selected ? "border-[var(--ink)]" : "border-[var(--line)] hover:border-[var(--ink)]"}`}
        disabled={busy}
        onClick={onSelect}
        type="button"
      >
        <img alt={asset.label} className="h-20 w-full object-cover" src={asset.public_url} />
        <p className="mt-1.5 truncate text-xs font-semibold">{asset.label}</p>
        <p className="text-xs text-[var(--muted)]">{asset.width && asset.height ? `${asset.width}×${asset.height}` : asset.purpose}</p>
      </button>
    </li>
  )
}

function MetaItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-[var(--muted)]">{label}</dt>
      <dd className="mt-1 break-words">{value}</dd>
    </div>
  )
}
