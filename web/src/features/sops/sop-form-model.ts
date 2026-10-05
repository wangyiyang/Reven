export type Sop = {
  id: string
  title: string
  kind: "procedure" | "checklist" | "script" | "method"
  status: "草稿" | "试行" | "正式"
  body: string
  tags: string[]
  created_at: string
  updated_at: string
}

export type SopKind = Sop["kind"]
export type SopStatus = Sop["status"]

export const kindLabels: Record<SopKind, string> = {
  procedure: "程序",
  checklist: "Checklist",
  script: "话术",
  method: "方法论",
}

export const SOP_KINDS: SopKind[] = ["procedure", "checklist", "script", "method"]
export const SOP_STATUSES: SopStatus[] = ["草稿", "试行", "正式"]

export type SopFormValues = {
  title: string
  kind: SopKind
  status: SopStatus
  tags: string
  body: string
}

export const EMPTY_SOP_FORM: SopFormValues = { title: "", kind: "procedure", status: "草稿", tags: "", body: "" }

function parseTags(value: string) {
  return value
    .split(/[,，]/)
    .map((tag) => tag.trim())
    .filter(Boolean)
}

export function sopFormToPayload(values: SopFormValues) {
  return {
    title: values.title,
    kind: values.kind,
    status: values.status,
    body: values.body,
    tags: parseTags(values.tags),
  }
}

export function sopToForm(sop: Sop): SopFormValues {
  return {
    title: sop.title,
    kind: sop.kind,
    status: sop.status,
    tags: sop.tags.join(", "),
    body: sop.body,
  }
}

export function validateSopForm(values: SopFormValues): string | null {
  return values.title.trim() && values.body.trim() ? null : "请填写标题和内容"
}
