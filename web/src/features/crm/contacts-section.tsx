import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import type { FormEvent } from "react"
import { useState } from "react"
import { toast } from "sonner"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import { ConfirmDialog } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"

import { createContact, crmKeys, deleteContact, emptyToNull, listContacts, updateContact } from "./crm-api"
import type { Contact, ContactInput } from "./types"

type ContactFormValues = {
  name: string
  role: string
  phone: string
  email: string
  wechat: string
  is_primary: boolean
  notes: string
}

const EMPTY_CONTACT: ContactFormValues = {
  name: "",
  role: "",
  phone: "",
  email: "",
  wechat: "",
  is_primary: false,
  notes: "",
}

export function ContactsSection({ customerId }: { customerId: string }) {
  const [form, setForm] = useState(EMPTY_CONTACT)
  const [editing, setEditing] = useState<Contact | null>(null)
  const [deleting, setDeleting] = useState<Contact | null>(null)
  const contactsQuery = useQuery({ queryKey: crmKeys.contacts(customerId), queryFn: () => listContacts(customerId) })
  const reset = () => { setForm(EMPTY_CONTACT); setEditing(null) }
  const createMutation = useCreateContact(customerId, reset)
  const updateMutation = useUpdateContact(customerId, reset)
  const deleteMutation = useDeleteContact(customerId, () => setDeleting(null))

  function submit() {
    const error = validateContact(form)
    if (error) return toast.error(error)
    const input = contactFormToInput(form)
    if (editing) updateMutation.mutate({ contactId: editing.id, input })
    else createMutation.mutate(input)
  }

  function startEdit(contact: Contact) {
    setEditing(contact)
    setForm(contactToForm(contact))
  }

  return (
    <Card>
      <CardHeader><h2 className="text-lg font-medium text-[var(--ink)]">联系人</h2></CardHeader>
      <CardContent className="space-y-5">
        <ContactForm busy={createMutation.isPending || updateMutation.isPending} editing={editing !== null} onCancel={reset} onChange={setForm} onSubmit={submit} values={form} />
        <ContactList contacts={contactsQuery.data} failed={contactsQuery.isError} loading={contactsQuery.isLoading} onDelete={setDeleting} onEdit={startEdit} onRetry={() => void contactsQuery.refetch()} />
      </CardContent>
      <ContactDeleteDialog contact={deleting} mutation={deleteMutation} onClose={() => setDeleting(null)} />
    </Card>
  )
}

type ContactFormProps = {
  values: ContactFormValues
  editing: boolean
  busy: boolean
  onChange: (values: ContactFormValues) => void
  onSubmit: () => void
  onCancel: () => void
}

function ContactForm(props: ContactFormProps) {
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    props.onSubmit()
  }

  return (
    <form className="space-y-4 rounded-lg border border-[var(--line)] p-4" onSubmit={submit}>
      <ContactIdentityFields {...props} />
      <ContactChannelFields {...props} />
      <ContactNotesField {...props} />
      <div className="flex gap-2"><Button disabled={props.busy} size="sm" type="submit">{props.editing ? "保存联系人" : "添加联系人"}</Button>{props.editing ? <Button onClick={props.onCancel} size="sm" type="button" variant="ghost">取消</Button> : null}</div>
    </form>
  )
}

function ContactIdentityFields({ values, onChange }: ContactFormProps) {
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <div className="space-y-2"><Label htmlFor="crm-contact-name">姓名</Label><Input id="crm-contact-name" onChange={(event) => onChange({ ...values, name: event.target.value })} required value={values.name} /></div>
      <div className="space-y-2"><Label htmlFor="crm-contact-role">职位</Label><Input id="crm-contact-role" onChange={(event) => onChange({ ...values, role: event.target.value })} value={values.role} /></div>
    </div>
  )
}

function ContactChannelFields({ values, onChange }: ContactFormProps) {
  return (
    <div className="grid gap-4 md:grid-cols-3">
      <div className="space-y-2"><Label htmlFor="crm-contact-phone">电话</Label><Input id="crm-contact-phone" onChange={(event) => onChange({ ...values, phone: event.target.value })} value={values.phone} /></div>
      <div className="space-y-2"><Label htmlFor="crm-contact-email">邮箱</Label><Input id="crm-contact-email" onChange={(event) => onChange({ ...values, email: event.target.value })} type="email" value={values.email} /></div>
      <div className="space-y-2"><Label htmlFor="crm-contact-wechat">微信</Label><Input id="crm-contact-wechat" onChange={(event) => onChange({ ...values, wechat: event.target.value })} value={values.wechat} /></div>
      <label className="flex items-center gap-2 whitespace-nowrap text-sm md:col-span-3"><input checked={values.is_primary} onChange={(event) => onChange({ ...values, is_primary: event.target.checked })} type="checkbox" />设为主要联系人</label>
    </div>
  )
}

function ContactNotesField({ values, onChange }: ContactFormProps) {
  return <div className="space-y-2"><Label htmlFor="crm-contact-notes">备注</Label><Textarea id="crm-contact-notes" onChange={(event) => onChange({ ...values, notes: event.target.value })} value={values.notes} /></div>
}

type ContactListProps = {
  contacts: Contact[] | undefined
  loading: boolean
  failed: boolean
  onRetry: () => void
  onEdit: (contact: Contact) => void
  onDelete: (contact: Contact) => void
}

function ContactList(props: ContactListProps) {
  if (props.loading) return <p className="text-sm text-[var(--muted)]">正在加载联系人…</p>
  if (props.failed) return <div className="flex items-center gap-2 text-sm text-[var(--muted)]"><span>联系人加载失败。</span><Button onClick={props.onRetry} size="sm" type="button" variant="outline">重试</Button></div>
  if (props.contacts?.length === 0) return <p className="text-sm text-[var(--muted)]">暂无联系人。</p>
  return <div className="grid gap-3 md:grid-cols-2">{props.contacts?.map((contact) => <ContactCard contact={contact} key={contact.id} onDelete={props.onDelete} onEdit={props.onEdit} />)}</div>
}

function ContactCard({ contact, onEdit, onDelete }: { contact: Contact; onEdit: (value: Contact) => void; onDelete: (value: Contact) => void }) {
  const channels = [contact.phone, contact.email, contact.wechat].filter(Boolean).join(" · ")
  return (
    <article aria-label={`${contact.name} 联系人摘要`} className="rounded-lg border border-[var(--line)] p-4">
      <div className="flex flex-wrap items-start justify-between gap-3"><div className="min-w-0"><p className="font-semibold">{contact.name}</p><p className="text-xs text-[var(--muted)]">{contact.role ?? "未填写职位"}</p></div>{contact.is_primary ? <Badge className="shrink-0 whitespace-nowrap">主要联系人</Badge> : null}</div>
      <p className="mt-3 break-words text-sm text-[var(--muted)]">{channels || "暂无联系方式"}</p>
      <div className="mt-3 flex justify-end gap-1"><Button onClick={() => onEdit(contact)} size="sm" type="button" variant="ghost">编辑</Button><Button onClick={() => onDelete(contact)} size="sm" type="button" variant="ghost">删除</Button></div>
    </article>
  )
}

function useCreateContact(customerId: string, onSaved: () => void) {
  const queryClient = useQueryClient()
  return useMutation({ mutationFn: (input: ContactInput) => createContact(customerId, input), onSuccess: async () => { await queryClient.invalidateQueries({ queryKey: crmKeys.contacts(customerId) }); onSaved(); toast.success("联系人已添加") }, onError: showError })
}

function useUpdateContact(customerId: string, onSaved: () => void) {
  const queryClient = useQueryClient()
  return useMutation({ mutationFn: ({ contactId, input }: { contactId: string; input: ContactInput }) => updateContact(customerId, contactId, input), onSuccess: async () => { await queryClient.invalidateQueries({ queryKey: crmKeys.contacts(customerId) }); onSaved(); toast.success("联系人已更新") }, onError: showError })
}

function useDeleteContact(customerId: string, onDeleted: () => void) {
  const queryClient = useQueryClient()
  return useMutation({ mutationFn: (contactId: string) => deleteContact(customerId, contactId), onSuccess: async () => { await Promise.all([queryClient.invalidateQueries({ queryKey: crmKeys.contacts(customerId) }), queryClient.invalidateQueries({ queryKey: crmKeys.followUps(customerId) })]); onDeleted(); toast.success("联系人已删除") }, onError: showError })
}

type DeleteMutation = ReturnType<typeof useDeleteContact>

function ContactDeleteDialog({ contact, mutation, onClose }: { contact: Contact | null; mutation: DeleteMutation; onClose: () => void }) {
  return <ConfirmDialog busy={mutation.isPending} confirmLabel={`确认删除「${contact?.name ?? ""}」`} description="历史跟进会保留联系人姓名快照。" onClose={onClose} onConfirm={() => { if (contact) mutation.mutate(contact.id) }} open={contact !== null} title="删除联系人" />
}

function contactToForm(contact: Contact): ContactFormValues {
  return { name: contact.name, role: contact.role ?? "", phone: contact.phone ?? "", email: contact.email ?? "", wechat: contact.wechat ?? "", is_primary: contact.is_primary, notes: contact.notes ?? "" }
}

function contactFormToInput(values: ContactFormValues): ContactInput {
  return { name: values.name.trim(), role: emptyToNull(values.role), phone: emptyToNull(values.phone), email: emptyToNull(values.email), wechat: emptyToNull(values.wechat), is_primary: values.is_primary, notes: emptyToNull(values.notes) }
}

function validateContact(values: ContactFormValues): string | null {
  if (!values.name.trim()) return "请填写联系人姓名"
  if (values.email && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(values.email.trim())) return "邮箱格式不正确"
  return null
}

function showError(error: unknown) {
  toast.error(error instanceof Error ? error.message : "请求失败")
}
