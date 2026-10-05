import type { FormEvent, KeyboardEvent } from "react"
import { useState } from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"

import { appendTag, removeTag, type TalentFormValues } from "./talent-form-model"
import { RATE_UNITS, TALENT_STATUSES, type RateUnit, type TalentStatus } from "./types"

type TalentFormProps = {
  values: TalentFormValues
  tagSuggestions: string[]
  editing: boolean
  busy: boolean
  /** 抽屉等窄容器场景强制单列；宽页（详情页编辑）保持响应式多列 */
  singleColumn?: boolean
  onChange: (values: TalentFormValues) => void
  onSubmit: () => void
  onCancel: () => void
}

const selectClassName = "h-10 w-full rounded-md border border-[var(--line)] bg-[var(--bg)] px-3 text-sm"

export function TalentForm(props: TalentFormProps) {
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    props.onSubmit()
  }

  return (
    <form className="space-y-4" onSubmit={submit}>
      <TalentIdentityFields {...props} />
      <TalentTagsField {...props} />
      <TalentProfileFields {...props} />
      <TalentRateFields {...props} />
      <div className="space-y-2">
        <Label htmlFor="talent-notes">备注</Label>
        <Textarea
          id="talent-notes"
          onChange={(event) => props.onChange({ ...props.values, notes: event.target.value })}
          placeholder="背景、合作偏好、风险点…"
          value={props.values.notes}
        />
      </div>
      <div className="flex justify-end gap-3 pt-2">
        <Button onClick={props.onCancel} type="button" variant="outline">{props.editing ? "取消编辑" : "取消"}</Button>
        <Button disabled={props.busy} type="submit">{props.editing ? "保存修改" : "添加人才"}</Button>
      </div>
    </form>
  )
}

function TalentIdentityFields({ values, singleColumn, onChange }: TalentFormProps) {
  return (
    <div className={singleColumn ? "grid gap-4" : "grid gap-4 md:grid-cols-3"}>
      <div className="space-y-2">
        <Label htmlFor="talent-name">姓名</Label>
        <Input
          id="talent-name"
          onChange={(event) => onChange({ ...values, name: event.target.value })}
          required
          value={values.name}
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="talent-status">状态</Label>
        <select
          className={selectClassName}
          id="talent-status"
          onChange={(event) => onChange({ ...values, status: event.target.value as TalentStatus })}
          value={values.status}
        >
          {TALENT_STATUSES.map((status) => <option key={status}>{status}</option>)}
        </select>
      </div>
      <div className="space-y-2">
        <Label htmlFor="talent-organization">机构</Label>
        <Input
          id="talent-organization"
          onChange={(event) => onChange({ ...values, organization: event.target.value })}
          placeholder="公司、工作室或自由职业"
          value={values.organization}
        />
      </div>
    </div>
  )
}

function TalentTagsField({ values, tagSuggestions, onChange }: TalentFormProps) {
  const [draft, setDraft] = useState("")
  const candidates = tagSuggestions.filter((tag) => !values.tags.includes(tag))

  function addDraft() {
    const tags = appendTag(values.tags, draft)
    if (tags !== values.tags) onChange({ ...values, tags })
    setDraft("")
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Enter") {
      event.preventDefault()
      addDraft()
    }
  }

  return (
    <div className="space-y-2">
      <Label htmlFor="talent-tags-input">标签</Label>
      <div className="flex gap-2">
        <Input
          id="talent-tags-input"
          list="talent-tag-suggestions"
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={onKeyDown}
          placeholder="输入后回车或点添加，如：插画、前端、翻译"
          value={draft}
        />
        <datalist id="talent-tag-suggestions">
          {candidates.map((tag) => <option key={tag} value={tag} />)}
        </datalist>
        <Button onClick={addDraft} type="button" variant="outline">添加标签</Button>
      </div>
      {values.tags.length > 0 ? (
        <div className="flex flex-wrap gap-2">
          {values.tags.map((tag) => (
            <Badge key={tag}>
              {tag}
              <button
                aria-label={`移除标签 ${tag}`}
                className="ml-1"
                onClick={() => onChange({ ...values, tags: removeTag(values.tags, tag) })}
                type="button"
              >
                ×
              </button>
            </Badge>
          ))}
        </div>
      ) : null}
    </div>
  )
}

function TalentProfileFields({ values, singleColumn, onChange }: TalentFormProps) {
  return (
    <div className={singleColumn ? "grid gap-4" : "grid gap-4 md:grid-cols-3"}>
      <div className="space-y-2">
        <Label htmlFor="talent-capability">能力</Label>
        <Input
          id="talent-capability"
          onChange={(event) => onChange({ ...values, capability: event.target.value })}
          placeholder="擅长什么、代表作"
          value={values.capability}
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="talent-engagement-terms">合作条件</Label>
        <Input
          id="talent-engagement-terms"
          onChange={(event) => onChange({ ...values, engagement_terms: event.target.value })}
          placeholder="结算方式、周期、限制"
          value={values.engagement_terms}
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="talent-availability">可用时间</Label>
        <Input
          id="talent-availability"
          onChange={(event) => onChange({ ...values, availability: event.target.value })}
          placeholder="每周可投入时间、时区"
          value={values.availability}
        />
      </div>
    </div>
  )
}

function TalentRateFields({ values, singleColumn, onChange }: TalentFormProps) {
  return (
    <div className={singleColumn ? "grid gap-4" : "grid gap-4 md:grid-cols-3"}>
      <div className="space-y-2">
        <Label htmlFor="talent-rate-amount">费率金额</Label>
        <Input
          id="talent-rate-amount"
          inputMode="decimal"
          min="0"
          onChange={(event) => onChange({ ...values, rate_amount: event.target.value })}
          placeholder="人民币，与单位同填同清"
          step="0.01"
          type="number"
          value={values.rate_amount}
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="talent-rate-unit">费率单位</Label>
        <select
          className={selectClassName}
          id="talent-rate-unit"
          onChange={(event) => onChange({ ...values, rate_unit: event.target.value as RateUnit | "" })}
          value={values.rate_unit}
        >
          <option value="">不填</option>
          {RATE_UNITS.map((unit) => <option key={unit}>{unit}</option>)}
        </select>
      </div>
      <div className="space-y-2">
        <Label htmlFor="talent-rating">评分</Label>
        <select
          className={selectClassName}
          id="talent-rating"
          onChange={(event) => onChange({ ...values, rating: event.target.value })}
          value={values.rating}
        >
          <option value="">未评分</option>
          {[1, 2, 3, 4, 5].map((score) => <option key={score} value={score}>{score} 星</option>)}
        </select>
      </div>
    </div>
  )
}
