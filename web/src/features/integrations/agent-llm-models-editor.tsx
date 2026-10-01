import { useState } from "react"
import { LoaderCircle, Pencil, Plus, Power, Radio, ShieldAlert, Star, Trash2 } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ConfirmDialog } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { modelRefOf } from "./agent-llm-model-entries"
import type { AgentModelEntry, ModelTestState } from "./types"

interface AgentLlmModelsEditorProps {
  /** 受控：当前编辑中的附加模型数组（本地暂存，随「保存配置」统一提交） */
  models: AgentModelEntry[]
  /** 待提交的模型独立密钥变更：ref → 新 key（空串 = 清除独立密钥） */
  pendingKeys: Record<string, string>
  /** 已配置独立密钥的 ref 列表（来自 integration.model_key_refs） */
  keyRefs: string[]
  /** 各模型最近一次行级测试结果 */
  tests: Record<string, ModelTestState>
  /** 正在执行行级测试的 ref */
  testingRef: string | null
  /** 全局动作锁 */
  disabled: boolean
  /** 默认模型 ref（去重校验与「设默认」可见性） */
  defaultRef: string
  /** models 或 pendingKeys 有未提交更改 */
  dirty: boolean
  onModelsChange: (models: AgentModelEntry[]) => void
  onPendingKeysChange: (pendingKeys: Record<string, string>) => void
  onSetDefault: (ref: string) => void
  onTest: (ref: string) => void
}

interface DraftEntry {
  provider: string
  model: string
  baseUrl: string
  enabled: boolean
  apiKey: string
  clearKey: boolean
}

const EMPTY_DRAFT: DraftEntry = { provider: "", model: "", baseUrl: "", enabled: true, apiKey: "", clearKey: false }

export function AgentLlmModelsEditor(props: AgentLlmModelsEditorProps) {
  const { models, pendingKeys, keyRefs, tests, testingRef, disabled, defaultRef, dirty } = props
  const [editIndex, setEditIndex] = useState<number | null>(null)
  const [draft, setDraft] = useState<DraftEntry>(EMPTY_DRAFT)
  const [draftError, setDraftError] = useState<string | null>(null)
  const [deleteIndex, setDeleteIndex] = useState<number | null>(null)

  const startEdit = (index: number) => {
    const entry = models[index]
    setEditIndex(index)
    setDraft({
      provider: entry.provider,
      model: entry.model,
      baseUrl: entry.base_url ?? "",
      enabled: entry.enabled,
      apiKey: "",
      clearKey: false,
    })
    setDraftError(null)
  }

  const startAdd = () => {
    setEditIndex(models.length)
    setDraft(EMPTY_DRAFT)
    setDraftError(null)
  }

  const cancelEdit = () => {
    setEditIndex(null)
    setDraft(EMPTY_DRAFT)
    setDraftError(null)
  }

  const commitDraft = () => {
    if (editIndex === null) return
    const provider = draft.provider.trim()
    const model = draft.model.trim()
    if (!provider || !model) {
      setDraftError("Provider 和模型不能为空。")
      return
    }
    const ref = modelRefOf(provider, model)
    if (ref === defaultRef) {
      setDraftError(`${ref} 已是默认模型，附加模型不能与之重复。`)
      return
    }
    const duplicated = models.some((entry, index) => index !== editIndex && modelRefOf(entry.provider, entry.model) === ref)
    if (duplicated) {
      setDraftError(`${ref} 已在列表中。`)
      return
    }
    const baseUrl = draft.baseUrl.trim()
    const entry: AgentModelEntry = {
      provider,
      model,
      ...(baseUrl ? { base_url: baseUrl } : {}),
      enabled: draft.enabled,
    }
    const next = editIndex === models.length ? [...models, entry] : models.map((item, index) => (index === editIndex ? entry : item))
    props.onModelsChange(next)

    // 独立密钥变更：清除优先于新值；编辑改了 ref 时丢弃旧 ref 的待提交变更
    const oldRef = editIndex < models.length ? modelRefOf(models[editIndex].provider, models[editIndex].model) : null
    const nextKeys = { ...pendingKeys }
    if (oldRef !== null && oldRef !== ref) delete nextKeys[oldRef]
    if (draft.clearKey) nextKeys[ref] = ""
    else if (draft.apiKey.trim()) nextKeys[ref] = draft.apiKey.trim()
    if (JSON.stringify(nextKeys) !== JSON.stringify(pendingKeys)) props.onPendingKeysChange(nextKeys)
    cancelEdit()
  }

  const toggleEnabled = (index: number) => {
    props.onModelsChange(models.map((entry, i) => (i === index ? { ...entry, enabled: !entry.enabled } : entry)))
  }

  const confirmDelete = () => {
    if (deleteIndex === null) return
    const ref = modelRefOf(models[deleteIndex].provider, models[deleteIndex].model)
    props.onModelsChange(models.filter((_, index) => index !== deleteIndex))
    if (ref in pendingKeys) {
      const nextKeys = { ...pendingKeys }
      delete nextKeys[ref]
      props.onPendingKeysChange(nextKeys)
    }
    if (editIndex !== null) cancelEdit()
    setDeleteIndex(null)
  }

  return (
    <section aria-label="附加模型列表" className="mt-8 border-t border-[var(--line)] pt-6 lg:col-span-2">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold">模型列表</h3>
          <p className="mt-1 text-xs text-[var(--muted)]">
            飞书 /model 指令可切换到已启用的模型；增删改与启停随「保存配置」统一生效。
          </p>
        </div>
        <Button aria-label="新增模型" disabled={disabled || editIndex !== null} onClick={startAdd} size="sm" variant="outline">
          <Plus aria-hidden size={14} />新增模型
        </Button>
      </div>
      <p className="mt-3 flex flex-wrap items-center gap-2 text-xs text-[var(--muted)]">
        默认模型：<span className="font-medium break-all text-[var(--ink)]">{defaultRef}</span>
        <Badge className="text-[var(--signal)]">默认</Badge>（在上方表单中编辑）
      </p>
      {dirty && <p className="mt-3 text-xs text-[var(--signal)]" role="status">模型列表有未保存的更改，点击「保存配置」后生效。</p>}

      {models.length === 0 && editIndex === null && (
        <p className="mt-4 text-sm text-[var(--muted)]">尚未配置附加模型。</p>
      )}

      <ul className="mt-4 space-y-3" role="list">
        {models.map((entry, index) => {
          const ref = modelRefOf(entry.provider, entry.model)
          if (editIndex === index) {
            return (
              <li key={`edit-${index}`}>
                <DraftForm
                  draft={draft}
                  error={draftError}
                  hasOverrideKey={keyRefs.includes(ref)}
                  onCancel={cancelEdit}
                  onChange={setDraft}
                  onCommit={commitDraft}
                />
              </li>
            )
          }
          return (
            <li className="rounded-md border border-[var(--line)] bg-[var(--faint)] p-4" key={ref}>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="flex flex-wrap items-center gap-2 text-sm font-medium">
                    <span className="break-all">{ref}</span>
                    {!entry.enabled && <Badge className="text-[var(--muted)]">已停用</Badge>}
                    {pendingKeys[ref] === ""
                      ? <Badge className="text-[var(--muted)]">将清除独立密钥</Badge>
                      : pendingKeys[ref]
                        ? <Badge className="text-[var(--signal)]">独立密钥待保存</Badge>
                        : keyRefs.includes(ref)
                          ? <Badge className="text-[var(--signal)]">独立密钥</Badge>
                          : <Badge className="text-[var(--muted)]">共用默认密钥</Badge>}
                  </p>
                  {entry.base_url && <p className="mt-1 break-all text-xs text-[var(--muted)]">{entry.base_url}</p>}
                  <ModelTestLine test={tests[ref]} testing={testingRef === ref} />
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <Button
                    aria-label={`测试${ref}连接`}
                    disabled={disabled}
                    onClick={() => props.onTest(ref)}
                    size="sm"
                    variant="ghost"
                  >
                    <Radio aria-hidden size={13} />测试
                  </Button>
                  <Button aria-label={`编辑${ref}`} disabled={disabled || editIndex !== null} onClick={() => startEdit(index)} size="sm" variant="ghost">
                    <Pencil aria-hidden size={13} />编辑
                  </Button>
                  {entry.enabled && (
                    <Button
                      aria-label={`把${ref}设为默认模型`}
                      disabled={disabled || dirty}
                      onClick={() => props.onSetDefault(ref)}
                      size="sm"
                      title={dirty ? "请先保存或放弃未保存的更改" : undefined}
                      variant="ghost"
                    >
                      <Star aria-hidden size={13} />设默认
                    </Button>
                  )}
                  <Button
                    aria-label={`${entry.enabled ? "停用" : "启用"}${ref}`}
                    disabled={disabled || editIndex !== null}
                    onClick={() => toggleEnabled(index)}
                    size="sm"
                    variant="ghost"
                  >
                    <Power aria-hidden size={13} />{entry.enabled ? "停用" : "启用"}
                  </Button>
                  <Button
                    aria-label={`删除${ref}`}
                    disabled={disabled || editIndex !== null}
                    onClick={() => setDeleteIndex(index)}
                    size="sm"
                    variant="ghost"
                  >
                    <Trash2 aria-hidden size={13} />删除
                  </Button>
                </div>
              </div>
            </li>
          )
        })}
        {editIndex === models.length && (
          <li key="edit-new">
            <DraftForm
              draft={draft}
              error={draftError}
              hasOverrideKey={false}
              onCancel={cancelEdit}
              onChange={setDraft}
              onCommit={commitDraft}
            />
          </li>
        )}
      </ul>

      <ConfirmDialog
        confirmLabel="确认删除模型"
        description="删除后该模型不再出现在飞书 /model 列表中，其独立密钥也会随保存一并清除。点击「保存配置」后生效。"
        onClose={() => setDeleteIndex(null)}
        onConfirm={confirmDelete}
        open={deleteIndex !== null}
        title={deleteIndex !== null ? `确认删除模型 ${modelRefOf(models[deleteIndex].provider, models[deleteIndex].model)}？` : "确认删除模型？"}
      />
    </section>
  )
}

function ModelTestLine({ test, testing }: { test?: ModelTestState; testing: boolean }) {
  if (testing) {
    return (
      <p className="mt-2 flex items-center gap-2 text-xs text-[var(--muted)]" role="status">
        <LoaderCircle aria-hidden className="animate-spin" size={12} />正在测试连接…
      </p>
    )
  }
  if (!test) return null
  if (test.status === "ok") {
    return (
      <p className="mt-2 text-xs text-[var(--signal)]" role="status">
        连接正常{test.latencyMs !== null ? ` · ${test.latencyMs} ms` : ""}
      </p>
    )
  }
  return (
    <p className="mt-2 text-xs text-[var(--danger)]" role="alert">
      连接失败{test.message ? `：${test.message}` : ""}
    </p>
  )
}

interface DraftFormProps {
  draft: DraftEntry
  error: string | null
  hasOverrideKey: boolean
  onChange: (draft: DraftEntry) => void
  onCommit: () => void
  onCancel: () => void
}

function DraftForm({ draft, error, hasOverrideKey, onChange, onCommit, onCancel }: DraftFormProps) {
  return (
    <div className="rounded-md border border-[var(--signal)] bg-[var(--bg)] p-4">
      <div className="grid gap-x-6 gap-y-4 sm:grid-cols-2">
        <div>
          <Label htmlFor="model-draft-provider">Provider</Label>
          <Input
            id="model-draft-provider"
            onChange={(event) => onChange({ ...draft, provider: event.target.value })}
            placeholder="deepseek-official"
            value={draft.provider}
          />
        </div>
        <div>
          <Label htmlFor="model-draft-model">模型</Label>
          <Input
            id="model-draft-model"
            onChange={(event) => onChange({ ...draft, model: event.target.value })}
            placeholder="deepseek-v4-pro"
            value={draft.model}
          />
        </div>
        <div>
          <Label htmlFor="model-draft-base-url">Base URL（可选）</Label>
          <Input
            id="model-draft-base-url"
            onChange={(event) => onChange({ ...draft, baseUrl: event.target.value })}
            placeholder="https://api.deepseek.com"
            value={draft.baseUrl}
          />
        </div>
        <div>
          <Label htmlFor="model-draft-api-key">独立 API Key（可选）</Label>
          <Input
            autoComplete="new-password"
            disabled={draft.clearKey}
            id="model-draft-api-key"
            onChange={(event) => onChange({ ...draft, apiKey: event.target.value })}
            placeholder={hasOverrideKey ? "留空则保留当前独立密钥" : "留空则共用默认密钥"}
            type="password"
            value={draft.apiKey}
          />
          <label className="mt-2 flex items-center gap-2 text-xs text-[var(--muted)]">
            <input
              checked={draft.clearKey}
              className="size-3.5 accent-[var(--signal)]"
              onChange={(event) => onChange({ ...draft, clearKey: event.target.checked })}
              type="checkbox"
            />
            清除独立密钥（改用默认密钥）
          </label>
        </div>
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 text-sm">
          <input
            checked={draft.enabled}
            className="size-4 accent-[var(--signal)]"
            onChange={(event) => onChange({ ...draft, enabled: event.target.checked })}
            type="checkbox"
          />
          启用该模型（停用后飞书 /model 不再列出）
        </label>
      </div>
      {error && <p className="mt-3 text-xs text-[var(--danger)]" role="alert">{error}</p>}
      <div className="mt-4 flex items-center gap-3">
        <Button onClick={onCommit} size="sm">
          <ShieldAlert aria-hidden size={13} />确认模型
        </Button>
        <Button onClick={onCancel} size="sm" variant="ghost">取消</Button>
      </div>
    </div>
  )
}
