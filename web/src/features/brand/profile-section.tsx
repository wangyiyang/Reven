import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useEffect, useState } from "react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { fetchBrandProfile, publishProfile, saveProfileDraft } from "./brand-api"
import { DEFAULT_PROFILE, type BrandProfilePayload } from "./types"

export function ProfileSection() {
  const client = useQueryClient()
  const profile = useQuery({ queryKey: ["brand-profile"], queryFn: fetchBrandProfile })
  const [form, setForm] = useState<BrandProfilePayload>(DEFAULT_PROFILE)

  useEffect(() => {
    const source = profile.data?.draft ?? profile.data?.published
    if (source) setForm(source.payload)
  }, [profile.data])

  const save = useMutation({
    mutationFn: () => saveProfileDraft(form),
    onSuccess: async () => {
      toast.success("品牌草稿已保存")
      await client.invalidateQueries({ queryKey: ["brand-profile"] })
    },
    onError: (error: Error) => toast.error(error.message),
  })
  const publish = useMutation({
    mutationFn: publishProfile,
    onSuccess: async () => {
      toast.success("品牌档案新版本已发布")
      await client.invalidateQueries({ queryKey: ["brand-profile"] })
    },
    onError: (error: Error) => toast.error(error.message),
  })

  if (profile.isLoading) return <Card><CardContent className="py-8 text-sm text-[var(--muted)]">正在读取品牌档案…</CardContent></Card>
  if (profile.isError) {
    return (
      <Card>
        <CardContent className="py-8 text-sm text-[var(--danger)]" role="alert">
          无法读取品牌档案：{profile.error.message}
          <Button className="ml-3" onClick={() => profile.refetch()} size="sm" variant="outline">重试</Button>
        </CardContent>
      </Card>
    )
  }

  const published = profile.data?.published ?? null
  const hasDraft = Boolean(profile.data?.draft)
  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold">品牌档案</h2>
            <p className="mt-1 text-xs text-[var(--muted)]">
              {published
                ? `当前已发布 v${published.version}${published.published_at ? ` · ${formatTime(published.published_at)}` : ""}`
                : "尚未发布品牌档案，请保存草稿后发布新版本"}
              {hasDraft && " · 存在未发布草稿"}
            </p>
          </div>
          <div className="flex gap-2">
            <Button disabled={save.isPending || publish.isPending} onClick={() => save.mutate()} size="sm" variant="outline">保存草稿</Button>
            <Button
              disabled={save.isPending || publish.isPending || !hasDraft}
              onClick={() => publish.mutate()}
              size="sm"
              title={hasDraft ? "发布当前草稿为新版本" : "请先保存草稿"}
            >发布新版本</Button>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="品牌名称">
            <Input
              aria-label="品牌名称"
              maxLength={100}
              onChange={(event) => setForm({ ...form, brand_name: event.target.value })}
              value={form.brand_name}
            />
          </Field>
          <Field label="默认署名">
            <Input
              aria-label="默认署名"
              maxLength={16}
              onChange={(event) => setForm({ ...form, default_author: event.target.value })}
              placeholder="品牌默认署名"
              value={form.default_author}
            />
          </Field>
          <Field label="一句话介绍">
            <Input
              aria-label="一句话介绍"
              maxLength={200}
              onChange={(event) => setForm({ ...form, tagline: event.target.value })}
              value={form.tagline}
            />
          </Field>
          <Field label="主色">
            <div className="flex items-center gap-2">
              <input
                aria-label="主色取色器"
                className="h-9 w-12 cursor-pointer border border-[var(--line)] bg-transparent"
                onChange={(event) => setForm({ ...form, colors: { ...form.colors, primary: event.target.value } })}
                type="color"
                value={form.colors.primary}
              />
              <Input
                aria-label="主色色值"
                onChange={(event) => setForm({ ...form, colors: { ...form.colors, primary: event.target.value } })}
                value={form.colors.primary}
              />
            </div>
          </Field>
          <Field label="正文字体">
            <Input
              aria-label="正文字体"
              onChange={(event) => setForm({ ...form, fonts: { ...form.fonts, body: event.target.value } })}
              placeholder="如 -apple-system, sans-serif"
              value={form.fonts.body}
            />
          </Field>
          <Field label="品牌主页">
            <Input
              aria-label="品牌主页"
              onChange={(event) => setForm({ ...form, website: event.target.value })}
              placeholder="https://…"
              value={form.website}
            />
          </Field>
        </div>
        <Field className="mt-4" label="品牌简介">
          <Textarea
            aria-label="品牌简介"
            maxLength={500}
            onChange={(event) => setForm({ ...form, intro: event.target.value })}
            rows={3}
            value={form.intro}
          />
        </Field>
      </CardContent>
    </Card>
  )
}

function Field({ label, children, className = "" }: { label: string; children: React.ReactNode; className?: string }) {
  return (
    <div className={className}>
      <Label className="mb-1.5 block text-xs text-[var(--muted)]">{label}</Label>
      {children}
    </div>
  )
}

function formatTime(value: string) {
  return new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeZone: "Asia/Shanghai" }).format(new Date(value))
}
