import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Plus, Trash2 } from "lucide-react"
import { useEffect, useState } from "react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Textarea } from "@/components/ui/textarea"
import {
  fetchBrandAssets,
  fetchChannelTemplate,
  publishChannelTemplate,
  saveBlogTemplateDraft,
  saveWeChatTemplateDraft,
} from "./brand-api"
import {
  DEFAULT_BLOG_TEMPLATE,
  DEFAULT_WECHAT_TEMPLATE,
  type BlogTemplatePayload,
  type BrandAsset,
  type FooterModule,
  type WeChatTemplatePayload,
} from "./types"

export function TemplatesSection() {
  const assets = useQuery({ queryKey: ["brand-assets"], queryFn: fetchBrandAssets })
  return (
    <Card>
      <CardHeader>
        <h2 className="text-base font-semibold">渠道模板</h2>
        <p className="mt-1 text-xs text-[var(--muted)]">微信排版与文末模块、博客署名与封面回落；发布后对新任务生效。</p>
      </CardHeader>
      <CardContent>
        <Tabs defaultValue="wechat">
          <TabsList>
            <TabsTrigger value="wechat">微信公众号</TabsTrigger>
            <TabsTrigger value="blog">个人博客</TabsTrigger>
          </TabsList>
          <TabsContent value="wechat">
            <WeChatTemplateForm assets={assets.data ?? []} />
          </TabsContent>
          <TabsContent value="blog">
            <BlogTemplateForm assets={assets.data ?? []} />
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  )
}

function WeChatTemplateForm({ assets }: { assets: BrandAsset[] }) {
  const client = useQueryClient()
  const template = useQuery({ queryKey: ["brand-template", "wechat"], queryFn: () => fetchChannelTemplate("wechat") })
  const [form, setForm] = useState<WeChatTemplatePayload>(DEFAULT_WECHAT_TEMPLATE)

  useEffect(() => {
    const source = template.data?.draft ?? template.data?.published
    if (source) setForm(normalizeWeChat(source.payload))
  }, [template.data])

  const save = useMutation({
    mutationFn: () => saveWeChatTemplateDraft(form),
    onSuccess: async () => {
      toast.success("微信模板草稿已保存")
      await client.invalidateQueries({ queryKey: ["brand-template", "wechat"] })
    },
    onError: (error: Error) => toast.error(error.message),
  })
  const publish = useMutation({
    mutationFn: () => publishChannelTemplate("wechat"),
    onSuccess: async () => {
      toast.success("微信模板已发布")
      await client.invalidateQueries({ queryKey: ["brand-template", "wechat"] })
    },
    onError: (error: Error) => toast.error(error.message),
  })

  if (template.isLoading) return <p className="py-6 text-sm text-[var(--muted)]">正在读取微信模板…</p>
  if (template.isError) return <p className="py-6 text-sm text-[var(--danger)]" role="alert">读取失败:{template.error.message}</p>

  const published = template.data?.published ?? null
  const updateModule = (index: number, patch: Partial<FooterModule>) =>
    setForm({ ...form, footer_modules: form.footer_modules.map((m, i) => (i === index ? { ...m, ...patch } : m)) })
  return (
    <div className="grid gap-5 pt-5">
      <TemplateStatus published={published} hasDraft={Boolean(template.data?.draft)} onPublish={() => publish.mutate()} onSave={() => save.mutate()} saving={save.isPending || publish.isPending} />
      <div className="grid gap-4 sm:grid-cols-3">
        <div>
          <Label className="mb-1.5 block text-xs text-[var(--muted)]">排版主色</Label>
          <div className="flex items-center gap-2">
            <input
              aria-label="排版主色取色器"
              className="h-9 w-12 cursor-pointer border border-[var(--line)] bg-transparent"
              onChange={(event) => setForm({ ...form, theme: { ...form.theme, primary_color: event.target.value } })}
              type="color"
              value={form.theme.primary_color}
            />
            <Input
              aria-label="排版主色色值"
              onChange={(event) => setForm({ ...form, theme: { ...form.theme, primary_color: event.target.value } })}
              value={form.theme.primary_color}
            />
          </div>
        </div>
        <div>
          <Label className="mb-1.5 block text-xs text-[var(--muted)]">正文字体（留空用品牌默认）</Label>
          <Input
            aria-label="微信正文字体"
            onChange={(event) => setForm({ ...form, theme: { ...form.theme, font_family: event.target.value } })}
            value={form.theme.font_family}
          />
        </div>
        <div>
          <Label className="mb-1.5 block text-xs text-[var(--muted)]">正文字号（12-24）</Label>
          <Input
            aria-label="微信正文字号"
            max={24}
            min={12}
            onChange={(event) => setForm({ ...form, theme: { ...form.theme, font_size: Number(event.target.value) || 16 } })}
            type="number"
            value={form.theme.font_size}
          />
        </div>
      </div>
      <div>
        <div className="mb-3 flex items-center justify-between">
          <Label className="text-xs text-[var(--muted)]">文末模块（按顺序追加到正文末尾；已存在时自动跳过）</Label>
          <div className="flex gap-2">
            <Button
              onClick={() => setForm({ ...form, footer_modules: [...form.footer_modules, newModule("text")] })}
              size="sm"
              variant="outline"
            ><Plus aria-hidden size={13} />文字模块</Button>
            <Button
              onClick={() => setForm({ ...form, footer_modules: [...form.footer_modules, newModule("image")] })}
              size="sm"
              variant="outline"
            ><Plus aria-hidden size={13} />图片模块</Button>
          </div>
        </div>
        {form.footer_modules.length === 0 && <p className="border border-dashed border-[var(--line)] p-4 text-sm text-[var(--muted)]">尚未配置文末模块。</p>}
        <ul className="grid gap-3">
          {form.footer_modules.map((module, index) => (
            <li className="border border-[var(--line)] p-4" key={module.key}>
              <div className="flex flex-wrap items-center gap-3">
                <label className="flex items-center gap-1.5 text-xs">
                  <input
                    aria-label={`模块${index + 1}启用`}
                    checked={module.enabled}
                    onChange={(event) => updateModule(index, { enabled: event.target.checked })}
                    type="checkbox"
                  />
                  启用
                </label>
                <span className="text-xs text-[var(--muted)]">{module.type === "text" ? "文字" : "图片"}</span>
                <Button
                  aria-label={`删除模块${index + 1}`}
                  onClick={() => setForm({ ...form, footer_modules: form.footer_modules.filter((_, i) => i !== index) })}
                  size="sm"
                  variant="ghost"
                ><Trash2 aria-hidden size={13} /></Button>
              </div>
              {module.type === "text" && (
                <Textarea
                  aria-label={`模块${index + 1}内容`}
                  className="mt-3"
                  maxLength={2000}
                  onChange={(event) => updateModule(index, { content: event.target.value })}
                  placeholder="如：欢迎关注「翊行代码」，回复「加群」…"
                  rows={2}
                  value={module.content}
                />
              )}
              {module.type === "image" && (
                <div className="mt-3">
                  <Select
                    onValueChange={(value) => updateModule(index, { asset_id: value })}
                    value={module.asset_id ?? ""}
                  >
                    <SelectTrigger aria-label={`模块${index + 1}素材`} className="w-72"><SelectValue placeholder="选择素材（如公众号二维码）" /></SelectTrigger>
                    <SelectContent>
                      {assets.filter((asset) => asset.enabled).map((asset) => (
                        <SelectItem key={asset.id} value={asset.id}>{asset.label}（{asset.purpose}）</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              )}
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}

function BlogTemplateForm({ assets }: { assets: BrandAsset[] }) {
  const client = useQueryClient()
  const template = useQuery({ queryKey: ["brand-template", "blog"], queryFn: () => fetchChannelTemplate("blog") })
  const [form, setForm] = useState<BlogTemplatePayload>(DEFAULT_BLOG_TEMPLATE)

  useEffect(() => {
    const source = template.data?.draft ?? template.data?.published
    if (source) setForm(normalizeBlog(source.payload))
  }, [template.data])

  const save = useMutation({
    mutationFn: () => saveBlogTemplateDraft(form),
    onSuccess: async () => {
      toast.success("博客模板草稿已保存")
      await client.invalidateQueries({ queryKey: ["brand-template", "blog"] })
    },
    onError: (error: Error) => toast.error(error.message),
  })
  const publish = useMutation({
    mutationFn: () => publishChannelTemplate("blog"),
    onSuccess: async () => {
      toast.success("博客模板已发布")
      await client.invalidateQueries({ queryKey: ["brand-template", "blog"] })
    },
    onError: (error: Error) => toast.error(error.message),
  })

  if (template.isLoading) return <p className="py-6 text-sm text-[var(--muted)]">正在读取博客模板…</p>
  if (template.isError) return <p className="py-6 text-sm text-[var(--danger)]" role="alert">读取失败:{template.error.message}</p>

  const published = template.data?.published ?? null
  const imageAssets = assets.filter((asset) => asset.enabled)
  return (
    <div className="grid gap-4 pt-5 sm:grid-cols-2">
      <TemplateStatus published={published} hasDraft={Boolean(template.data?.draft)} onPublish={() => publish.mutate()} onSave={() => save.mutate()} saving={save.isPending || publish.isPending} />
      <div>
        <Label className="mb-1.5 block text-xs text-[var(--muted)]">博客署名（留空用品牌默认署名）</Label>
        <Input
          aria-label="博客署名"
          maxLength={50}
          onChange={(event) => setForm({ ...form, author: event.target.value })}
          value={form.author}
        />
      </div>
      <AssetSelect
        assets={imageAssets}
        label="默认封面素材（稿件无封面时回落）"
        onChange={(value) => setForm({ ...form, cover_fallback_asset_id: value })}
        value={form.cover_fallback_asset_id}
      />
      <AssetSelect
        assets={imageAssets}
        label="OG 分享图素材（留空则由封面推导）"
        onChange={(value) => setForm({ ...form, og_image_asset_id: value })}
        value={form.og_image_asset_id}
      />
    </div>
  )
}

function AssetSelect({ assets, label, value, onChange }: { assets: BrandAsset[]; label: string; value: string | null; onChange: (value: string | null) => void }) {
  return (
    <div>
      <Label className="mb-1.5 block text-xs text-[var(--muted)]">{label}</Label>
      <Select onValueChange={(next) => onChange(next === "__none__" ? null : next)} value={value ?? "__none__"}>
        <SelectTrigger aria-label={label} className="w-full"><SelectValue /></SelectTrigger>
        <SelectContent>
          <SelectItem value="__none__">不设置</SelectItem>
          {assets.map((asset) => <SelectItem key={asset.id} value={asset.id}>{asset.label}（{asset.purpose}）</SelectItem>)}
        </SelectContent>
      </Select>
    </div>
  )
}

function TemplateStatus({ published, hasDraft, onSave, onPublish, saving }: {
  published: { version: number } | null
  hasDraft: boolean
  onSave: () => void
  onPublish: () => void
  saving: boolean
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--line)] pb-4 sm:col-span-2">
      <p className="text-xs text-[var(--muted)]">
        {published ? `当前已发布 v${published.version}` : "尚未发布，该渠道使用默认样式与行为"}
        {hasDraft && " · 存在未发布草稿"}
      </p>
      <div className="flex gap-2">
        <Button disabled={saving} onClick={onSave} size="sm" variant="outline">保存草稿</Button>
        <Button disabled={saving || !hasDraft} onClick={onPublish} size="sm" title={hasDraft ? "发布当前草稿" : "请先保存草稿"}>发布新版本</Button>
      </div>
    </div>
  )
}

function newModule(type: "text" | "image"): FooterModule {
  return { key: `${type}-${Date.now()}`, type, content: "", asset_id: null, enabled: true }
}

function normalizeWeChat(payload: Record<string, unknown>): WeChatTemplatePayload {
  const theme = (payload.theme ?? {}) as Record<string, unknown>
  const modules = Array.isArray(payload.footer_modules) ? payload.footer_modules : []
  return {
    theme: {
      primary_color: typeof theme.primary_color === "string" ? theme.primary_color : "#00E676",
      font_family: typeof theme.font_family === "string" ? theme.font_family : "",
      font_size: typeof theme.font_size === "number" ? theme.font_size : 16,
    },
    footer_modules: modules.map((raw): FooterModule => {
      const module = (raw ?? {}) as Record<string, unknown>
      return {
        key: typeof module.key === "string" && module.key ? module.key : `module-${Date.now()}`,
        type: module.type === "image" ? "image" : "text",
        content: typeof module.content === "string" ? module.content : "",
        asset_id: typeof module.asset_id === "string" ? module.asset_id : null,
        enabled: module.enabled !== false,
      }
    }),
  }
}

function normalizeBlog(payload: Record<string, unknown>): BlogTemplatePayload {
  return {
    author: typeof payload.author === "string" ? payload.author : "",
    cover_fallback_asset_id: typeof payload.cover_fallback_asset_id === "string" ? payload.cover_fallback_asset_id : null,
    og_image_asset_id: typeof payload.og_image_asset_id === "string" ? payload.og_image_asset_id : null,
  }
}
