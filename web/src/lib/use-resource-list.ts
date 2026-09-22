import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import type { FormEvent } from "react"
import { useState } from "react"
import { toast } from "sonner"

import { apiRequest } from "@/lib/api"

export type ResourceEntity = { id: string }
export type ResourceFilters = Record<string, string>

export type ResourceListMessages = {
  created: string
  updated: string
  deleted: string
  saveFailed: string
  updateFailed: string
  deleteFailed: string
}

export type UseResourceListOptions<TEntity extends ResourceEntity, TForm, TFilters extends ResourceFilters = ResourceFilters> = {
  /** 资源名，同时作为 query key 前缀（如 "projects"），前缀命中该资源全部缓存变体 */
  key: string
  /** API 路径（如 "/projects"），PUT/DELETE 自动拼接 /:id */
  path: string
  initialForm: TForm
  initialFilters?: TFilters
  toPayload: (form: TForm) => unknown
  toForm: (entity: TEntity) => TForm
  /** 返回错误文案则阻断提交并 toast；返回 null 放行 */
  validate?: (form: TForm) => string | null
  messages: ResourceListMessages
  /** create/update 成功后回调，携带服务端返回实体（供详情缓存写入、关闭抽屉等扩展） */
  onSaved?: (entity: TEntity) => void
  /** delete 成功后回调 */
  onDeleted?: (id: string) => void
}

export function normalizeErrorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback
}

export function useResourceList<TEntity extends ResourceEntity, TForm, TFilters extends ResourceFilters = ResourceFilters>(
  options: UseResourceListOptions<TEntity, TForm, TFilters>,
) {
  const { key, path, initialForm, toPayload, toForm, validate, messages, onSaved, onDeleted } = options
  const queryClient = useQueryClient()
  const [form, setForm] = useState<TForm>(initialForm)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [deleting, setDeleting] = useState<TEntity | null>(null)
  const [filters, setFilters] = useState<TFilters>(options.initialFilters ?? ({} as TFilters))

  const itemsQuery = useQuery({
    queryKey: [key, filters],
    queryFn: () => {
      const params = new URLSearchParams()
      for (const [name, value] of Object.entries(filters)) {
        const trimmed = value.trim()
        if (trimmed) params.set(name, trimmed)
      }
      const suffix = params.size ? `?${params.toString()}` : ""
      return apiRequest<TEntity[]>(`${path}${suffix}`)
    },
  })

  async function invalidateList() {
    await queryClient.invalidateQueries({ queryKey: [key] })
  }

  const createMutation = useMutation({
    mutationFn: (input: TForm) =>
      apiRequest<TEntity>(path, { method: "POST", body: JSON.stringify(toPayload(input)) }),
    onSuccess: async (entity) => {
      setForm(initialForm)
      await invalidateList()
      onSaved?.(entity)
      toast.success(messages.created)
    },
    onError: (error) => toast.error(normalizeErrorMessage(error, messages.saveFailed)),
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, input }: { id: string; input: TForm }) =>
      apiRequest<TEntity>(`${path}/${id}`, { method: "PUT", body: JSON.stringify(toPayload(input)) }),
    onSuccess: async (entity) => {
      setForm(initialForm)
      setEditingId(null)
      await invalidateList()
      onSaved?.(entity)
      toast.success(messages.updated)
    },
    onError: (error) => toast.error(normalizeErrorMessage(error, messages.updateFailed)),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => apiRequest(`${path}/${id}`, { method: "DELETE" }),
    onMutate: async (id: string) => {
      // 乐观删除：远端库延迟高，先移除行再给服务端对账
      await queryClient.cancelQueries({ queryKey: [key] })
      const previous = queryClient.getQueriesData<TEntity[]>({ queryKey: [key] })
      // 前缀可能命中同资源的非列表缓存（如 talents 的详情/交互条目），只过滤数组
      queryClient.setQueriesData<TEntity[]>({ queryKey: [key] }, (old) =>
        Array.isArray(old) ? old.filter((item) => item.id !== id) : old,
      )
      return { previous }
    },
    onSuccess: (_data, id) => {
      onDeleted?.(id)
      toast.success(messages.deleted)
    },
    onError: (error, _id, context) => {
      context?.previous?.forEach(([entryKey, data]) => queryClient.setQueryData(entryKey, data))
      toast.error(normalizeErrorMessage(error, messages.deleteFailed))
    },
    onSettled: async () => {
      await invalidateList()
    },
  })

  function setField<TKey extends keyof TForm>(name: TKey, value: TForm[TKey]) {
    setForm((current) => ({ ...current, [name]: value }))
  }

  function startEdit(entity: TEntity) {
    setEditingId(entity.id)
    setForm(toForm(entity))
  }

  function cancelEdit() {
    setEditingId(null)
    setForm(initialForm)
  }

  function submit(event: Pick<FormEvent<HTMLFormElement>, "preventDefault">) {
    event.preventDefault()
    const validationError = validate?.(form)
    if (validationError) {
      toast.error(validationError)
      return
    }
    if (editingId) {
      updateMutation.mutate({ id: editingId, input: form })
      return
    }
    createMutation.mutate(form)
  }

  function confirmRemove() {
    if (!deleting) return
    deleteMutation.mutate(deleting.id, { onSuccess: () => setDeleting(null) })
  }

  return {
    itemsQuery,
    filters,
    setFilters,
    form,
    setField,
    editingId,
    startEdit,
    cancelEdit,
    submit,
    isSaving: createMutation.isPending || updateMutation.isPending,
    deleting,
    requestRemove: (entity: TEntity) => setDeleting(entity),
    cancelRemove: () => setDeleting(null),
    confirmRemove,
    isRemoving: deleteMutation.isPending,
  }
}
