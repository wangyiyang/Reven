import { Check, LoaderCircle, Pencil, Plus, Power, Radio, Trash2, X } from "lucide-react"
import { useEffect, useState, type FormEvent } from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ConfirmDialog } from "@/components/ui/dialog"
import { Drawer } from "@/components/ui/drawer"
import { ErrorPanel } from "@/components/ui/error-panel"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import type { FeishuBindingInput } from "./feishu-bindings-api"
import type { BindingTestResult, FeishuResourceBinding, Integration } from "./types"
import { useFeishuBindings } from "./use-feishu-bindings"

interface FeishuBindingsSectionProps {
  /** 飞书集成当前状态（未配置时为 undefined）：用于判定是否允许创建绑定 */
  integration?: Integration
  /** 卡片全局动作锁：任一集成操作进行中时禁用绑定区动作 */
  disabled: boolean
}

const STAGE_LABELS: Record<string, string> = {
  fields: "字段校验",
  search: "只读查询",
  create: "写入测试记录",
  delete: "删除测试记录",
}

function stageLabel(stage: string): string {
  return STAGE_LABELS[stage] ?? stage
}

export function FeishuBindingsSection({ integration, disabled }: FeishuBindingsSectionProps) {
  const controller = useFeishuBindings()
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [editing, setEditing] = useState<FeishuResourceBinding | null>(null)
  const [deleting, setDeleting] = useState<FeishuResourceBinding | null>(null)

  // 创建绑定的前置：飞书机器人已启用且凭证已配置（后端 409 FEISHU_BOT_NOT_ENABLED 兜底，前端提前置灰）
  const botReady = integration?.secret_configured === true && integration.public_config.enabled === true
  const rowBusy = disabled || controller.busy

  const openCreate = () => {
    setEditing(null)
    setDrawerOpen(true)
  }
  const openEdit = (binding: FeishuResourceBinding) => {
    setEditing(binding)
    setDrawerOpen(true)
  }
  const closeDrawer = () => {
    setDrawerOpen(false)
    setEditing(null)
  }
  const save = async (input: FeishuBindingInput, enabled: boolean) => {
    const saved = editing
      ? await controller.execute({ action: "update", id: editing.id, input })
      : await controller.execute({ action: "create", input, enabled })
    if (saved) closeDrawer()
    return saved
  }

  return (
    <section aria-label="多维表格绑定" className="mt-8 border-t border-[var(--line)] pt-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold">多维表格绑定</h3>
          <p className="mt-1 max-w-xl text-xs text-[var(--muted)]">
            RSS 候选将直接写入绑定的多维表格；同一用途同时只能启用一个绑定。
          </p>
        </div>
        <Button
          aria-label="新增多维表格绑定"
          disabled={rowBusy || !botReady}
          onClick={openCreate}
          size="sm"
          title={botReady ? undefined : "请先保存 App ID / App Secret 并启用机器人"}
          variant="outline"
        >
          <Plus aria-hidden size={14} />新增绑定
        </Button>
      </div>

      {!botReady && (
        <p className="mt-3 text-xs text-[var(--muted)]" role="status">
          需先在上方保存 App ID / App Secret 并勾选「启用机器人」后才能创建绑定；绑定测试同样依赖可用的飞书凭证。
        </p>
      )}

      {controller.bindings.isLoading && (
        <p aria-busy="true" className="mt-4 text-sm text-[var(--muted)]">正在读取绑定列表…</p>
      )}
      {controller.bindings.isError && (
        <div className="mt-4">
          <ErrorPanel
            message={controller.bindings.error.message}
            retry={() => void controller.bindings.refetch()}
            title="绑定列表读取失败"
          />
        </div>
      )}
      {controller.bindings.isSuccess && controller.bindings.data.length === 0 && (
        <p className="mt-4 text-sm text-[var(--muted)]">尚未配置绑定。</p>
      )}
      {controller.bindings.isSuccess && controller.bindings.data.length > 0 && (
        <ul className="mt-4 space-y-3" role="list">
          {controller.bindings.data.map((binding) => (
            <BindingRow
              binding={binding}
              disabled={rowBusy}
              key={binding.id}
              onDelete={() => setDeleting(binding)}
              onEdit={() => openEdit(binding)}
              onTest={() => controller.test(binding.id)}
              onToggle={() => void controller.execute({ action: binding.enabled ? "disable" : "enable", id: binding.id })}
              test={controller.tests[binding.id]}
              testing={controller.testingId === binding.id}
            />
          ))}
        </ul>
      )}

      <BindingFormDrawer
        busy={controller.busy}
        editing={editing}
        onClose={closeDrawer}
        onSubmit={save}
        open={drawerOpen}
      />
      <ConfirmDialog
        busy={controller.busy}
        confirmLabel="确认删除绑定"
        description={`删除后 RSS 候选将不再写入该多维表格（${deleting?.config.app_token ?? ""} / ${deleting?.config.table_id ?? ""}），已写入的数据保留在飞书侧。`}
        onClose={() => setDeleting(null)}
        onConfirm={() => {
          if (!deleting) return
          void controller.execute({ action: "delete", id: deleting.id }).then((deleted) => deleted && setDeleting(null))
        }}
        open={deleting !== null}
        title="删除多维表格绑定？"
      />
    </section>
  )
}

interface BindingRowProps {
  binding: FeishuResourceBinding
  disabled: boolean
  testing: boolean
  test?: BindingTestResult
  onEdit: () => void
  onToggle: () => void
  onDelete: () => void
  onTest: () => void
}

function BindingRow(props: BindingRowProps) {
  const { binding } = props
  return (
    <li className="rounded-md border border-[var(--line)] bg-[var(--faint)] p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="flex flex-wrap items-center gap-2 text-sm font-medium">
            <span className="break-all">应用 {binding.config.app_token}</span>
            {binding.enabled
              ? <Badge className="text-[var(--signal)]">已启用</Badge>
              : <Badge className="text-[var(--muted)]">已停用</Badge>}
          </p>
          <p className="mt-1 break-all text-xs text-[var(--muted)]">数据表 {binding.config.table_id}</p>
          <BindingTestPanel result={props.test} testing={props.testing} />
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            aria-label={`测试绑定 ${binding.config.app_token}`}
            disabled={props.disabled || props.testing}
            onClick={props.onTest}
            size="sm"
            variant="ghost"
          >
            <Radio aria-hidden size={13} />测试连接
          </Button>
          <Button aria-label={`编辑绑定 ${binding.config.app_token}`} disabled={props.disabled} onClick={props.onEdit} size="sm" variant="ghost">
            <Pencil aria-hidden size={13} />编辑
          </Button>
          <Button
            aria-label={`${binding.enabled ? "停用" : "启用"}绑定 ${binding.config.app_token}`}
            disabled={props.disabled}
            onClick={props.onToggle}
            size="sm"
            variant="ghost"
          >
            <Power aria-hidden size={13} />{binding.enabled ? "停用" : "启用"}
          </Button>
          <Button
            aria-label={`删除绑定 ${binding.config.app_token}`}
            disabled={props.disabled}
            onClick={props.onDelete}
            size="sm"
            variant="ghost"
          >
            <Trash2 aria-hidden size={13} />删除
          </Button>
        </div>
      </div>
    </li>
  )
}

function BindingTestPanel({ result, testing }: { result?: BindingTestResult; testing: boolean }) {
  if (testing) {
    return (
      <p className="mt-2 flex items-center gap-2 text-xs text-[var(--muted)]" role="status">
        <LoaderCircle aria-hidden className="animate-spin" size={12} />正在测试绑定…
      </p>
    )
  }
  if (!result) return null
  if (result.success) {
    return (
      <p className="mt-2 flex items-center gap-2 text-xs text-[var(--signal)]" role="status">
        <Check aria-hidden size={12} />测试通过：字段校验、只读查询、写入与删除测试记录均成功。
      </p>
    )
  }
  return (
    <div className="mt-2 rounded-md border border-[var(--danger)] bg-[var(--bg)] p-3" role="alert">
      <p className="text-xs font-semibold text-[var(--danger)]">
        测试未通过{result.failed_stage ? `：${stageLabel(result.failed_stage)}阶段失败` : ""}
      </p>
      {result.stages.length > 0 && (
        <ul className="mt-2 space-y-1 text-xs">
          {result.stages.map((stage) => (
            <li className={`flex items-start gap-1.5 ${stage.success ? "text-[var(--signal)]" : "text-[var(--danger)]"}`} key={stage.stage}>
              {stage.success
                ? <Check aria-hidden className="mt-0.5 shrink-0" size={12} />
                : <X aria-hidden className="mt-0.5 shrink-0" size={12} />}
              <span>{stageLabel(stage.stage)}{stage.message ? `：${stage.message}` : ""}</span>
            </li>
          ))}
        </ul>
      )}
      {result.message && <p className="mt-2 text-xs text-[var(--danger)]">{result.message}</p>}
    </div>
  )
}

interface BindingFormDrawerProps {
  open: boolean
  busy: boolean
  editing: FeishuResourceBinding | null
  onClose: () => void
  onSubmit: (input: FeishuBindingInput, enabled: boolean) => Promise<boolean>
}

function BindingFormDrawer(props: BindingFormDrawerProps) {
  return (
    <Drawer onClose={props.onClose} open={props.open} title={props.editing ? "编辑多维表格绑定" : "新建多维表格绑定"}>
      <BindingForm busy={props.busy} editing={props.editing} onClose={props.onClose} onSubmit={props.onSubmit} />
    </Drawer>
  )
}

// 表单状态挂在 Drawer children 内：关闭（含退出动画结束）后由 Radix 卸载，
// 下次打开重新挂载，表单自然回到初始值
function BindingForm({ busy, editing, onClose, onSubmit }: Omit<BindingFormDrawerProps, "open">) {
  const [appToken, setAppToken] = useState("")
  const [tableId, setTableId] = useState("")
  const [enabled, setEnabled] = useState(false)
  useEffect(() => {
    setAppToken(editing?.config.app_token ?? "")
    setTableId(editing?.config.table_id ?? "")
    setEnabled(false)
  }, [editing])
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    await onSubmit({ app_token: appToken.trim(), table_id: tableId.trim() }, enabled)
  }
  return (
    <form className="space-y-4" onSubmit={submit}>
      <div className="space-y-2">
        <Label htmlFor="binding-app-token">应用 App Token</Label>
        <Input
          id="binding-app-token"
          maxLength={256}
          onChange={(event) => setAppToken(event.target.value)}
          placeholder="bascn…（多维表格 URL 中的 app 标识）"
          required
          value={appToken}
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="binding-table-id">数据表 Table ID</Label>
        <Input
          id="binding-table-id"
          maxLength={256}
          onChange={(event) => setTableId(event.target.value)}
          placeholder="tbl…（多维表格 URL 中的 table 标识）"
          required
          value={tableId}
        />
      </div>
      {editing === null && (
        <label className="flex items-center gap-2 text-sm">
          <input
            checked={enabled}
            className="size-4 accent-[var(--signal)]"
            onChange={(event) => setEnabled(event.target.checked)}
            type="checkbox"
          />
          创建后立即启用（同一用途同时只能启用一个绑定）
        </label>
      )}
      {editing !== null && (
        <p className="text-xs text-[var(--muted)]">启停状态请使用绑定列表中的「启用 / 停用」按钮调整。</p>
      )}
      <div className="flex justify-end gap-3 pt-2">
        <Button onClick={onClose} type="button" variant="outline">取消</Button>
        <Button disabled={busy} type="submit">{editing ? "保存绑定" : "创建绑定"}</Button>
      </div>
    </form>
  )
}
