import { useEffect, useId, useRef, useState } from "react"
import type { RefObject } from "react"
import { Check, LoaderCircle, Radio, Save, Send, ShieldAlert, Trash2 } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ConfirmDialog } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import type { RssRunHealth } from "./integration-api"
import type { FieldDefinition, Integration, Provider, ProviderController, ProviderDefinition } from "./types"

interface IntegrationCardProps {
  definition: ProviderDefinition
  controller: ProviderController
}

export function IntegrationCard({ definition, controller }: IntegrationCardProps) {
  const { integration, runHealth, disabled, busy } = controller.state
  const form = useIntegrationForm(definition, integration)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const deleteButtonRef = useRef<HTMLButtonElement>(null)
  const saveButtonRef = useRef<HTMLButtonElement>(null)
  const feishu = definition.provider === "feishu_bot"
  const deleteLabel = `删除${definition.title}密钥`

  const secretPayload = Object.fromEntries(definition.secretFields.map((field) => [field.key, form.secrets[field.key] ?? ""]))
  const secretComplete = definition.secretFields.every((field) => form.secrets[field.key]?.trim())
  const publicConfigComplete = hasCompletePublicConfig(definition, form.publicConfig)
  const publicConfig = publicConfigForSave(definition, form.publicConfig)
  const runHealthSummary = RUN_HEALTH_PROVIDERS.includes(definition.provider) && runHealth !== undefined
    ? describeRunHealth(runHealth)
    : null

  return (
    <article className="integration-card group relative mb-6 rounded-lg border border-[var(--line)] bg-[var(--bg)] p-6 shadow-sm">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold">{definition.title}</h2>
          <p className="mt-1 max-w-xl text-sm text-[var(--muted)]">{definition.description}</p>
        </div>
        <ConnectionBadge integration={integration} />
      </header>

      <div className="mt-8 grid gap-x-10 gap-y-6 lg:grid-cols-2">
        {definition.publicFields.map((field) => (
          <PublicField field={field} form={form} key={field.key} />
        ))}
        {definition.secretFields.map((field, index) => (
          <div key={field.key}>
            <Label htmlFor={`${form.formId}-secret-${field.key}`}>{field.label}</Label>
            <Input
              autoComplete="new-password"
              id={`${form.formId}-secret-${field.key}`}
              onChange={(event) => form.setSecret(field.key, event.target.value)}
              placeholder={integration?.secret_configured ? "留空则保留当前密钥" : field.placeholder}
              type="password"
              value={form.secrets[field.key] ?? ""}
            />
            {index === definition.secretFields.length - 1 && (
              <p className="mt-2 flex items-center gap-2 text-xs text-[var(--muted)]">
                <ShieldAlert aria-hidden size={13} />{integration?.secret_hint ?? "尚未配置 · 保存后不可回看"}
              </p>
            )}
          </div>
        ))}
      </div>

      {integration?.last_error && (
        <p className="mt-6 rounded-md border-l-2 border-[var(--danger)] bg-[var(--faint)] px-4 py-3 text-sm text-[var(--danger)]" role="alert">
          {integration.last_error}
        </p>
      )}
      {feishu && (
        <p className="mt-5 flex items-center gap-2 text-xs font-semibold text-[var(--muted)]">
          <Send aria-hidden size={14} />将向已保存的接收人发送一条测试消息，请先保存接收人配置。
        </p>
      )}
      {runHealthSummary && (
        <p className={`mt-5 text-xs ${runHealthSummary.degraded ? "text-[var(--danger)]" : "text-[var(--muted)]"}`}>
          {runHealthSummary.text}
        </p>
      )}

      <footer className="mt-7">
        {!publicConfigComplete && <p className="mb-3 text-xs text-[var(--danger)]">{`请填写 ${formatFieldLabels(definition.publicFields.filter((field) => !field.optional))}后保存配置。`}</p>}
        {!integration?.secret_configured && publicConfigComplete && <p className="mb-3 text-xs text-[var(--muted)]">{`请先保存配置并设置 ${formatFieldLabels(definition.secretFields)} 后${feishu ? "发送测试消息" : "测试连接"}。`}</p>}
        <div className="flex flex-wrap items-center gap-3">
        <Button aria-label={`保存${definition.title}配置`} disabled={disabled || !publicConfigComplete} onClick={() => controller.actions.save(publicConfig)} ref={saveButtonRef}>
          <Save aria-hidden size={15} />保存配置
        </Button>
        <Button
          aria-label={`${integration?.secret_configured ? "替换" : "保存"}${definition.title}密钥`}
          disabled={disabled || !publicConfigComplete || !secretComplete}
          onClick={() => controller.actions.replace(publicConfig, secretPayload)}
          variant="outline"
        >
          <ShieldAlert aria-hidden size={15} />{integration?.secret_configured ? "替换密钥" : "保存密钥"}
        </Button>
        <Button
          aria-label={feishu ? "发送飞书测试消息" : `测试${definition.title}连接`}
          disabled={disabled || !integration?.secret_configured}
          onClick={() => controller.actions.test()}
          variant="outline"
        >
          <Radio aria-hidden size={15} />{feishu ? "发送测试消息" : "测试连接"}
        </Button>
        {integration?.secret_configured && <Button aria-label={deleteLabel} disabled={disabled} onClick={() => setConfirmOpen(true)} ref={deleteButtonRef} variant="danger"><Trash2 aria-hidden size={15} />删除密钥</Button>}
        {busy !== null && <LoaderCircle aria-label="处理中" className="animate-spin text-[var(--muted)]" size={18} />}
        </div>
      </footer>

      <ConfirmDialog
        busy={busy !== null}
        confirmLabel={`确认${deleteLabel}`}
        description="删除后，依赖此密钥的集成将无法运行。公共配置仍会保留。"
        onClose={() => setConfirmOpen(false)}
        onConfirm={() => handleDeleteConfirm(controller.actions.remove, () => setConfirmOpen(false), deleteButtonRef, saveButtonRef)}
        open={confirmOpen}
        returnFocusRef={deleteButtonRef}
        title={`确认${deleteLabel}？`}
      />
    </article>
  )
}

// 删除成功后：触发按钮即将卸载，把焦点还给稳定的“保存配置”按钮
async function handleDeleteConfirm(
  remove: () => Promise<boolean>,
  close: () => void,
  triggerRef: RefObject<HTMLButtonElement | null>,
  stableRef: RefObject<HTMLButtonElement | null>,
) {
  const trigger = triggerRef.current
  close()
  if (!await remove()) return
  window.setTimeout(() => {
    const active = document.activeElement
    if (active === document.body || active === trigger || !active?.isConnected) {
      stableRef.current?.focus()
    }
  }, 0)
}

interface IntegrationForm {
  formId: string
  publicConfig: Record<string, string>
  secrets: Record<string, string>
  setField: (key: string, value: string) => void
  setSecret: (key: string, value: string) => void
}

function useIntegrationForm(definition: ProviderDefinition, integration?: Integration): IntegrationForm {
  const [publicConfig, setPublicConfig] = useState<Record<string, string>>({})
  const [secrets, setSecrets] = useState<Record<string, string>>({})
  const formId = useId()
  useEffect(() => {
    setPublicConfig(Object.fromEntries(
      definition.publicFields.map((field) => {
        const stored = integration?.public_config[field.key]
        const value = field.type === "string_list" && Array.isArray(stored)
          ? stored.join("\n")
          : String(stored ?? field.defaultValue ?? "")
        return [field.key, value]
      }),
    ))
    setSecrets({})
  }, [definition, integration])
  return {
    formId,
    publicConfig,
    secrets,
    setField: (key, value) => setPublicConfig((current) => ({ ...current, [key]: value })),
    setSecret: (key, value) => setSecrets((current) => ({ ...current, [key]: value })),
  }
}

function PublicField({ field, form }: { field: FieldDefinition; form: IntegrationForm }) {
  const id = `${form.formId}-${field.key}`
  if (field.type === "string_list") {
    return (
      <div>
        <Label htmlFor={id}>{field.label}</Label>
        <Textarea
          id={id}
          onChange={(event) => form.setField(field.key, event.target.value)}
          placeholder={field.placeholder}
          value={form.publicConfig[field.key] ?? ""}
        />
      </div>
    )
  }
  if (field.type === "checkbox") {
    return (
      <div className="flex h-10 items-center gap-2 self-end">
        <input
          checked={form.publicConfig[field.key] === "true"}
          className="size-4 shrink-0 accent-[var(--signal)]"
          id={id}
          onChange={(event) => form.setField(field.key, String(event.target.checked))}
          type="checkbox"
        />
        <Label htmlFor={id}>{field.label}</Label>
      </div>
    )
  }
  return (
    <div>
      <Label htmlFor={id}>{field.label}</Label>
      <Input
        id={id}
        onChange={(event) => form.setField(field.key, event.target.value)}
        placeholder={field.placeholder}
        required={!field.optional}
        type={field.type === "number" ? "number" : "text"}
        value={form.publicConfig[field.key] ?? ""}
      />
    </div>
  )
}

const RUN_HEALTH_PROVIDERS: Provider[] = ["translate_baidu", "translate_aliyun", "embedding"]

function describeRunHealth(run: RssRunHealth | null): { text: string; degraded: boolean } {
  if (run === null) return { text: "最近每日任务：暂无运行记录", degraded: false }
  const statusText = { completed: "成功", partial: "降级", running: "进行中", screening: "进行中" }[run.status]
  const errorTypes = [...new Set(run.errors.map((error) => error.error_type))]
  const suffix = run.status === "partial" && errorTypes.length > 0 ? ` · ${errorTypes.join("、")}` : ""
  return { text: `最近每日任务：${statusText}${suffix}`, degraded: run.status === "partial" }
}

function hasCompletePublicConfig(definition: ProviderDefinition, publicConfig: Record<string, string>) {
  return definition.publicFields.every((field) => {
    if (field.optional || field.type === "checkbox") return true
    const value = publicConfig[field.key]?.trim() ?? ""
    if (!value) return false
    return field.type !== "number" || !Number.isNaN(Number(value))
  })
}

function publicConfigForSave(definition: ProviderDefinition, publicConfig: Record<string, string>): Record<string, unknown> {
  return Object.fromEntries(definition.publicFields.flatMap((field): [string, unknown][] => {
    if (field.type === "string_list") return [[field.key, parseStringList(publicConfig[field.key])]]
    if (field.type === "checkbox") return [[field.key, publicConfig[field.key] === "true"]]
    const value = publicConfig[field.key]?.trim() ?? ""
    if (field.optional && !value) return []
    return [[field.key, field.type === "number" ? Number(value) : value]]
  }))
}

function parseStringList(value: string | undefined): string[] {
  return (value ?? "").split(/[\s,，]+/).map((item) => item.trim()).filter(Boolean)
}

function formatFieldLabels(fields: FieldDefinition[]) {
  const labels = fields.map((field) => field.label)
  return labels.length > 1 ? `${labels.slice(0, -1).join("、")} 和${labels.at(-1)}` : labels[0]
}

function ConnectionBadge({ integration }: { integration?: Integration }) {
  if (!integration) return <Badge className="text-[var(--muted)]">未配置</Badge>
  const ok = integration.connection_status === "连接正常"
  const style = ok ? "text-[var(--signal)]" : integration.connection_status === "连接失败" ? "text-[var(--danger)]" : "text-[var(--muted)]"
  return (
    <div className="justify-self-start text-right sm:justify-self-end">
      <Badge className={style}>{ok && <Check aria-hidden size={12} />}{integration.connection_status}</Badge>
      {integration.last_tested_at && (
        <p className="mt-2 text-xs text-[var(--muted)]">
          {formatShanghai(integration.last_tested_at)}
          {integration.last_latency_ms !== null && ` · ${integration.last_latency_ms} ms`}
        </p>
      )}
    </div>
  )
}

function formatShanghai(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "short",
    timeStyle: "short",
    timeZone: "Asia/Shanghai",
  }).format(new Date(value))
}
