import { useEffect, useId, useState } from "react"
import { ArrowUpRight, Check, LoaderCircle, Radio, Save, Send, ShieldAlert, Trash2, Wrench } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ConfirmDialog } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import type { Integration, ProviderDefinition } from "./types"

interface IntegrationCardProps {
  definition: ProviderDefinition
  integration?: Integration
  egressIp?: string | null
  busyAction?: string
  onSave: (provider: string, publicConfig: Record<string, string>) => void
  onReplace: (provider: string, publicConfig: Record<string, string>, secret: Record<string, string>) => void
  onDelete: (provider: string) => void
  onTest: (provider: string) => void
  onBootstrap: () => void
}

export function IntegrationCard(props: IntegrationCardProps) {
  const form = useIntegrationForm(props.definition, props.integration)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const busy = props.busyAction?.startsWith(props.definition.provider)
  const deleteLabel = `删除${props.definition.title}密钥`
  return (
    <article className="integration-card group relative border-t border-[var(--ink)] py-8">
      <CardHeader definition={props.definition} integration={props.integration} />
      <ConfigFields definition={props.definition} egressIp={props.egressIp} form={form} integration={props.integration} />
      <StatusNotices definition={props.definition} integration={props.integration} />
      <CardActions
        busy={busy}
        definition={props.definition}
        form={form}
        integration={props.integration}
        onBootstrap={props.onBootstrap}
        onDelete={() => setConfirmOpen(true)}
        onReplace={props.onReplace}
        onSave={props.onSave}
        onTest={props.onTest}
      />
      <ConfirmDialog
        busy={busy}
        confirmLabel={`确认${deleteLabel}`}
        description="删除后，依赖此密钥的自动同步或发布会立即停止。公共配置仍会保留。"
        onClose={() => setConfirmOpen(false)}
        onConfirm={() => { setConfirmOpen(false); props.onDelete(props.definition.provider) }}
        open={confirmOpen}
        title={`确认${deleteLabel}？`}
      />
    </article>
  )
}

interface IntegrationForm {
  formId: string
  publicConfig: Record<string, string>
  secret: string
  setField: (key: string, value: string) => void
  setSecret: (value: string) => void
}

function useIntegrationForm(definition: ProviderDefinition, integration?: Integration): IntegrationForm {
  const [publicConfig, setPublicConfig] = useState<Record<string, string>>({})
  const [secret, setSecret] = useState("")
  const formId = useId()
  useEffect(() => {
    setPublicConfig(Object.fromEntries(
      definition.publicFields.map((field) => [field.key, String(integration?.public_config[field.key] ?? "")]),
    ))
    setSecret("")
  }, [definition, integration])
  return {
    formId,
    publicConfig,
    secret,
    setField: (key, value) => setPublicConfig((current) => ({ ...current, [key]: value })),
    setSecret,
  }
}

function CardHeader({ definition, integration }: { definition: ProviderDefinition; integration?: Integration }) {
  return (
    <header className="grid gap-5 sm:grid-cols-[5rem_1fr_auto]">
      <span className="font-display text-5xl leading-none text-[var(--line-strong)]" aria-hidden>{definition.number}</span>
      <div>
        <p className="text-[11px] font-bold tracking-[0.22em] text-[var(--red)] uppercase">{definition.eyebrow}</p>
        <h2 className="font-display mt-1 text-3xl text-[var(--ink)]">{definition.title}</h2>
        <p className="mt-2 max-w-xl text-sm leading-6 text-[var(--muted)]">{definition.description}</p>
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
        <div key={field.key}>
          <Label htmlFor={`${props.form.formId}-${field.key}`}>{field.label}</Label>
          <Input
            id={`${props.form.formId}-${field.key}`}
            onChange={(event) => props.form.setField(field.key, event.target.value)}
            placeholder={field.placeholder}
            required
            value={props.form.publicConfig[field.key] ?? ""}
          />
          {props.definition.provider === "github" && field.key === "default_branch" && (
            <p className="mt-2 text-xs text-[var(--muted)]">以该分支作为发布基线，不在客户端猜测仓库默认值。</p>
          )}
        </div>
      ))}
      <SecretField definition={props.definition} form={props.form} integration={props.integration} />
      {props.definition.provider === "wechat" && <EgressIp value={props.egressIp} />}
    </div>
  )
}

function SecretField(props: {
  definition: ProviderDefinition
  integration?: Integration
  form: IntegrationForm
}) {
  const field = props.definition.secretField
  return (
    <div>
      <Label htmlFor={`${props.form.formId}-secret`}>{field.label}</Label>
      <Input
        autoComplete="new-password"
        id={`${props.form.formId}-secret`}
        onChange={(event) => props.form.setSecret(event.target.value)}
        placeholder={props.integration?.secret_configured ? "留空则保留当前密钥" : field.placeholder}
        type="password"
        value={props.form.secret}
      />
      <p className="mt-2 flex items-center gap-2 text-xs text-[var(--muted)]">
        <ShieldAlert aria-hidden size={13} />{props.integration?.secret_hint ?? "尚未配置 · 保存后不可回看"}
      </p>
    </div>
  )
}

function StatusNotices({ definition, integration }: { definition: ProviderDefinition; integration?: Integration }) {
  return (
    <>
      {integration?.last_error && (
        <p className="mt-6 border-l-2 border-[var(--red)] bg-[var(--red-soft)] px-4 py-3 text-sm text-[var(--red)]" role="alert">
          {integration.last_error}
        </p>
      )}
      {definition.provider === "feishu" && (
        <p className="mt-5 flex items-center gap-2 text-xs font-semibold text-[var(--blue)]">
          <Send aria-hidden size={14} />测试飞书会主动发送一条消息。
        </p>
      )}
    </>
  )
}

interface CardActionsProps {
  busy?: boolean
  definition: ProviderDefinition
  form: IntegrationForm
  integration?: Integration
  onSave: IntegrationCardProps["onSave"]
  onReplace: IntegrationCardProps["onReplace"]
  onTest: IntegrationCardProps["onTest"]
  onBootstrap: () => void
  onDelete: () => void
}

function CardActions(props: CardActionsProps) {
  const { definition, form, integration } = props
  const secretPayload = { [definition.secretField.key]: form.secret }
  return (
    <footer className="mt-7 flex flex-wrap items-center gap-3">
      <Button aria-label={`保存${definition.title}配置`} disabled={props.busy} onClick={() => props.onSave(definition.provider, form.publicConfig)}>
        <Save aria-hidden size={15} />保存配置
      </Button>
      <Button
        aria-label={`${integration?.secret_configured ? "替换" : "保存"}${definition.title}密钥`}
        disabled={props.busy || !form.secret}
        onClick={() => props.onReplace(definition.provider, form.publicConfig, secretPayload)}
        variant="outline"
      >
        <ShieldAlert aria-hidden size={15} />{integration?.secret_configured ? "替换密钥" : "保存密钥"}
      </Button>
      <TestButton busy={props.busy} definition={definition} onTest={props.onTest} />
      {definition.provider === "notion" && <Button disabled={props.busy} onClick={props.onBootstrap} variant="outline"><Wrench aria-hidden size={15} />初始化字段</Button>}
      {integration?.secret_configured && <Button aria-label={`删除${definition.title}密钥`} onClick={props.onDelete} variant="danger"><Trash2 aria-hidden size={15} />删除密钥</Button>}
      {props.busy && <LoaderCircle aria-label="处理中" className="animate-spin text-[var(--blue)]" size={18} />}
    </footer>
  )
}

function TestButton(props: Pick<CardActionsProps, "busy" | "definition" | "onTest">) {
  const feishu = props.definition.provider === "feishu"
  return (
    <Button
      aria-label={feishu ? "发送飞书测试消息" : `测试${props.definition.title}连接`}
      disabled={props.busy}
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
  const style = ok ? "text-[var(--blue)]" : integration.connection_status === "连接失败" ? "text-[var(--red)]" : "text-[var(--muted)]"
  return (
    <div className="justify-self-start text-right sm:justify-self-end">
      <Badge className={style}>{ok && <Check aria-hidden size={12} />}{integration.connection_status}</Badge>
      {integration.last_tested_at && <p className="mt-2 text-[10px] tracking-wide text-[var(--muted)]">{formatShanghai(integration.last_tested_at)}</p>}
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
      <div className="mt-2 flex min-h-8 items-center gap-2 border-b border-[var(--line)] pb-2 font-mono text-sm">
        <ArrowUpRight aria-hidden size={15} className="text-[var(--blue)]" />{value ?? "暂时无法获取"}
      </div>
      <p className="mt-2 text-xs text-[var(--muted)]">请将该地址加入微信公众号 IP 白名单。</p>
    </div>
  )
}
