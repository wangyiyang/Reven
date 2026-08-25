import { useEffect, useId, useRef, useState } from "react"
import type { RefObject } from "react"
import { ArrowUpRight, Check, LoaderCircle, Radio, Save, Send, ShieldAlert, Trash2, Wrench } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ConfirmDialog } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import type { RssRunHealth } from "./integration-api"
import type { FieldDefinition, Integration, Provider, ProviderDefinition } from "./types"

interface IntegrationCardProps {
  definition: ProviderDefinition
  integration?: Integration
  egressIp?: string | null
  runHealth?: RssRunHealth | null
  actionsDisabled: boolean
  busyAction?: string
  onSave: (provider: Provider, publicConfig: Record<string, unknown>) => void
  onReplace: (provider: Provider, publicConfig: Record<string, unknown>, secret: Record<string, string>) => void
  onDelete: (provider: Provider) => Promise<boolean>
  onTest: (provider: Provider) => void
  onBootstrap: () => void
}

export function IntegrationCard(props: IntegrationCardProps) {
  const form = useIntegrationForm(props.definition, props.integration)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const deleteButtonRef = useRef<HTMLButtonElement>(null)
  const saveButtonRef = useRef<HTMLButtonElement>(null)
  const busy = props.busyAction?.startsWith(props.definition.provider)
  const deleteLabel = `删除${props.definition.title}密钥`
  return (
    <article className="integration-card group relative mb-6 rounded-lg border border-[var(--line)] bg-[var(--bg)] p-6 shadow-sm">
      <CardHeader definition={props.definition} integration={props.integration} />
      <ConfigFields definition={props.definition} egressIp={props.egressIp} form={form} integration={props.integration} />
      <StatusNotices definition={props.definition} integration={props.integration} />
      <RunHealthNotice definition={props.definition} run={props.runHealth} />
      <CardActions
        actionsDisabled={props.actionsDisabled}
        busy={busy}
        definition={props.definition}
        form={form}
        integration={props.integration}
        onBootstrap={props.onBootstrap}
        onDelete={() => setConfirmOpen(true)}
        deleteButtonRef={deleteButtonRef}
        onReplace={props.onReplace}
        onSave={props.onSave}
        onTest={props.onTest}
        saveButtonRef={saveButtonRef}
      />
      <ConfirmDialog
        busy={busy}
        confirmLabel={`确认${deleteLabel}`}
        description="删除后，依赖此密钥的自动同步或发布会立即停止。公共配置仍会保留。"
        onClose={() => setConfirmOpen(false)}
        onConfirm={() => handleDeleteConfirm(props, () => setConfirmOpen(false), deleteButtonRef, saveButtonRef)}
        open={confirmOpen}
        returnFocusRef={deleteButtonRef}
        title={`确认${deleteLabel}？`}
      />
    </article>
  )
}

async function handleDeleteConfirm(
  props: IntegrationCardProps,
  close: () => void,
  triggerRef: RefObject<HTMLButtonElement | null>,
  stableRef: RefObject<HTMLButtonElement | null>,
) {
  const trigger = triggerRef.current
  close()
  if (!await props.onDelete(props.definition.provider)) return
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
      definition.publicFields.map((field) => [
        field.key,
        String(integration?.public_config[field.key] ?? field.defaultValue ?? ""),
      ]),
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

function CardHeader({ definition, integration }: { definition: ProviderDefinition; integration?: Integration }) {
  return (
    <header className="flex flex-wrap items-start justify-between gap-4">
      <div>
        <h2 className="text-lg font-semibold">{definition.title}</h2>
        <p className="mt-1 max-w-xl text-sm text-[var(--muted)]">{definition.description}</p>
      </div>
      <ConnectionBadge integration={integration} />
    </header>
  )
}

function ConfigFields(props: {
  definition: ProviderDefinition
  integration?: Integration
  egressIp?: string | null
  form: IntegrationForm
}) {
  return (
    <div className="mt-8 grid gap-x-10 gap-y-6 lg:grid-cols-2">
      {props.definition.publicFields.map((field) => (
        <PublicField definition={props.definition} field={field} form={props.form} key={field.key} />
      ))}
      <SecretFields definition={props.definition} form={props.form} integration={props.integration} />
      {props.definition.provider === "wechat" && <EgressIp value={props.egressIp} />}
    </div>
  )
}

function PublicField({ definition, field, form }: { definition: ProviderDefinition; field: FieldDefinition; form: IntegrationForm }) {
  const id = `${form.formId}-${field.key}`
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
      {definition.provider === "github" && field.key === "default_branch" && (
        <p className="mt-2 text-xs text-[var(--muted)]">以该分支作为发布基线，不在客户端猜测仓库默认值。</p>
      )}
    </div>
  )
}

function SecretFields(props: {
  definition: ProviderDefinition
  integration?: Integration
  form: IntegrationForm
}) {
  const fields = props.definition.secretFields
  return (
    <>
      {fields.map((field, index) => (
        <div key={field.key}>
          <Label htmlFor={`${props.form.formId}-secret-${field.key}`}>{field.label}</Label>
          <Input
            autoComplete="new-password"
            id={`${props.form.formId}-secret-${field.key}`}
            onChange={(event) => props.form.setSecret(field.key, event.target.value)}
            placeholder={props.integration?.secret_configured ? "留空则保留当前密钥" : field.placeholder}
            type="password"
            value={props.form.secrets[field.key] ?? ""}
          />
          {index === fields.length - 1 && (
            <p className="mt-2 flex items-center gap-2 text-xs text-[var(--muted)]">
              <ShieldAlert aria-hidden size={13} />{props.integration?.secret_hint ?? "尚未配置 · 保存后不可回看"}
            </p>
          )}
        </div>
      ))}
    </>
  )
}

function StatusNotices({ definition, integration }: { definition: ProviderDefinition; integration?: Integration }) {
  return (
    <>
      {integration?.last_error && (
        <p className="mt-6 rounded-md border-l-2 border-[var(--danger)] bg-[var(--faint)] px-4 py-3 text-sm text-[var(--danger)]" role="alert">
          {integration.last_error}
        </p>
      )}
      {definition.provider === "feishu" && (
        <p className="mt-5 flex items-center gap-2 text-xs font-semibold text-[var(--muted)]">
          <Send aria-hidden size={14} />测试飞书会主动发送一条消息。
        </p>
      )}
    </>
  )
}

const RUN_HEALTH_PROVIDERS: Provider[] = ["translate_baidu", "translate_aliyun", "embedding"]

function RunHealthNotice({ definition, run }: { definition: ProviderDefinition; run?: RssRunHealth | null }) {
  if (!RUN_HEALTH_PROVIDERS.includes(definition.provider) || run === undefined) return null
  if (run === null) return <p className="mt-5 text-xs text-[var(--muted)]">最近每日任务：暂无运行记录</p>
  const statusText = { completed: "成功", partial: "降级", running: "进行中", screening: "进行中" }[run.status]
  const degraded = run.status === "partial"
  const errorTypes = [...new Set(run.errors.map((error) => error.error_type))]
  return (
    <p className={`mt-5 text-xs ${degraded ? "text-[var(--danger)]" : "text-[var(--muted)]"}`}>
      最近每日任务：{statusText}
      {degraded && errorTypes.length > 0 && ` · ${errorTypes.join("、")}`}
    </p>
  )
}

interface CardActionsProps {
  actionsDisabled: boolean
  busy?: boolean
  definition: ProviderDefinition
  form: IntegrationForm
  integration?: Integration
  onSave: IntegrationCardProps["onSave"]
  onReplace: IntegrationCardProps["onReplace"]
  onTest: IntegrationCardProps["onTest"]
  onBootstrap: () => void
  onDelete: () => void
  deleteButtonRef: RefObject<HTMLButtonElement | null>
  saveButtonRef: RefObject<HTMLButtonElement | null>
}

function CardActions(props: CardActionsProps) {
  const { definition, form, integration } = props
  const secretPayload = Object.fromEntries(definition.secretFields.map((field) => [field.key, form.secrets[field.key] ?? ""]))
  const secretComplete = definition.secretFields.every((field) => form.secrets[field.key]?.trim())
  const publicConfigComplete = hasCompletePublicConfig(definition, form.publicConfig)
  const publicConfig = publicConfigForSave(definition, form.publicConfig)
  return (
    <footer className="mt-7">
      {!publicConfigComplete && <p className="mb-3 text-xs text-[var(--danger)]">{`请填写 ${formatFieldLabels(definition.publicFields.filter((field) => !field.optional))}后保存配置。`}</p>}
      {!integration?.secret_configured && publicConfigComplete && <p className="mb-3 text-xs text-[var(--muted)]">{`请先保存配置并设置 ${formatFieldLabels(definition.secretFields)} 后测试连接。`}</p>}
      <div className="flex flex-wrap items-center gap-3">
      <Button aria-label={`保存${definition.title}配置`} disabled={props.actionsDisabled || !publicConfigComplete} onClick={() => props.onSave(definition.provider, publicConfig)} ref={props.saveButtonRef}>
        <Save aria-hidden size={15} />保存配置
      </Button>
      <Button
        aria-label={`${integration?.secret_configured ? "替换" : "保存"}${definition.title}密钥`}
        disabled={props.actionsDisabled || !publicConfigComplete || !secretComplete}
        onClick={() => props.onReplace(definition.provider, publicConfig, secretPayload)}
        variant="outline"
      >
        <ShieldAlert aria-hidden size={15} />{integration?.secret_configured ? "替换密钥" : "保存密钥"}
      </Button>
      <TestButton actionsDisabled={props.actionsDisabled} definition={definition} integration={integration} onTest={props.onTest} />
      {definition.provider === "notion" && <Button disabled={props.actionsDisabled} onClick={props.onBootstrap} variant="outline"><Wrench aria-hidden size={15} />初始化字段</Button>}
      {integration?.secret_configured && <Button aria-label={`删除${definition.title}密钥`} disabled={props.actionsDisabled} onClick={props.onDelete} ref={props.deleteButtonRef} variant="danger"><Trash2 aria-hidden size={15} />删除密钥</Button>}
      {props.busy && <LoaderCircle aria-label="处理中" className="animate-spin text-[var(--muted)]" size={18} />}
      </div>
    </footer>
  )
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
    if (field.type === "checkbox") return [[field.key, publicConfig[field.key] === "true"]]
    const value = publicConfig[field.key]?.trim() ?? ""
    if (field.optional && !value) return []
    return [[field.key, field.type === "number" ? Number(value) : value]]
  }))
}

function formatFieldLabels(fields: FieldDefinition[]) {
  const labels = fields.map((field) => field.label)
  return labels.length > 1 ? `${labels.slice(0, -1).join("、")} 和${labels.at(-1)}` : labels[0]
}

function TestButton(props: Pick<CardActionsProps, "actionsDisabled" | "definition" | "integration" | "onTest">) {
  const feishu = props.definition.provider === "feishu"
  return (
    <Button
      aria-label={feishu ? "发送飞书测试消息" : `测试${props.definition.title}连接`}
      disabled={props.actionsDisabled || !props.integration?.secret_configured}
      onClick={() => props.onTest(props.definition.provider)}
      variant="outline"
    >
      <Radio aria-hidden size={15} />{feishu ? "发送测试消息" : "测试连接"}
    </Button>
  )
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

function EgressIp({ value }: { value?: string | null }) {
  return (
    <div>
      <Label>出口 IP</Label>
      <div className="mt-2 flex min-h-8 items-center gap-2 rounded-md border border-[var(--line)] px-3 py-2 font-mono text-sm">
        <ArrowUpRight aria-hidden size={15} className="text-[var(--muted)]" />{value ?? "暂时无法获取"}
      </div>
      <p className="mt-2 text-xs text-[var(--muted)]">请将该地址加入微信公众号 IP 白名单。</p>
    </div>
  )
}
