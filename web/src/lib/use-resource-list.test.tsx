import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, renderHook, waitFor } from "@testing-library/react"
import { HttpResponse, http } from "msw"
import type { ReactNode } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { toast } from "sonner"

import { server } from "@/test/server"

import { normalizeErrorMessage, useResourceList } from "./use-resource-list"

vi.mock("sonner", () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
  },
}))

type Thing = { id: string; name: string }
type ThingForm = { name: string }

const thing: Thing = { id: "t-1", name: "Alpha" }

const messages = {
  created: "已添加",
  updated: "已更新",
  deleted: "已删除",
  saveFailed: "保存失败",
  updateFailed: "更新失败",
  deleteFailed: "删除失败",
}

function setup(options?: {
  initialFilters?: Record<string, string>
  validate?: (form: ThingForm) => string | null
  onSaved?: (entity: Thing) => void
  onDeleted?: (id: string) => void
}) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  )
  const hook = renderHook(
    () =>
      useResourceList<Thing, ThingForm>({
        key: "things",
        path: "/things",
        initialForm: { name: "" },
        initialFilters: options?.initialFilters,
        toPayload: (form) => ({ name: form.name }),
        toForm: (entity) => ({ name: entity.name }),
        validate: options?.validate,
        onSaved: options?.onSaved,
        onDeleted: options?.onDeleted,
        messages,
      }),
    { wrapper },
  )
  return { queryClient, hook }
}

describe("useResourceList", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    server.use(http.get("/api/things", () => HttpResponse.json([thing])))
  })

  it("loads items and serializes only non-empty filters into the query string", async () => {
    const seen: { url: URL | null } = { url: null }
    server.use(
      http.get("/api/things", ({ request }) => {
        seen.url = new URL(request.url)
        return HttpResponse.json([thing])
      }),
    )

    const { hook } = setup({ initialFilters: { status: "进行中", query: "  " } })

    await waitFor(() => expect(hook.result.current.itemsQuery.data).toEqual([thing]))
    expect(seen.url?.searchParams.get("status")).toBe("进行中")
    expect(seen.url?.searchParams.has("query")).toBe(false)
  })

  it("creates an item, resets the form and refreshes the list", async () => {
    let requestBody: unknown = null
    let items = [thing]
    server.use(
      http.post("/api/things", async ({ request }) => {
        requestBody = await request.json()
        items = [...items, { id: "t-2", name: "Beta" }]
        return HttpResponse.json({ id: "t-2", name: "Beta" }, { status: 201 })
      }),
      http.get("/api/things", () => HttpResponse.json(items)),
    )

    const { hook } = setup()
    await waitFor(() => expect(hook.result.current.itemsQuery.data).toHaveLength(1))

    act(() => hook.result.current.setField("name", "Beta"))
    act(() => hook.result.current.submit({ preventDefault() {} }))

    await waitFor(() => expect(hook.result.current.itemsQuery.data).toHaveLength(2))
    expect(requestBody).toEqual({ name: "Beta" })
    expect(toast.success).toHaveBeenCalledWith("已添加")
    expect(hook.result.current.form).toEqual({ name: "" })
    expect(hook.result.current.editingId).toBeNull()
  })

  it("surfaces the normalized server message when create fails", async () => {
    server.use(http.post("/api/things", () => HttpResponse.json({ code: "dup", message: "名称重复" }, { status: 400 })))

    const { hook } = setup()
    await waitFor(() => expect(hook.result.current.itemsQuery.data).toEqual([thing]))

    act(() => hook.result.current.setField("name", "Alpha"))
    act(() => hook.result.current.submit({ preventDefault() {} }))

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("名称重复"))
  })

  it("blocks submit when validate returns an error", async () => {
    let posted = false
    server.use(
      http.post("/api/things", () => {
        posted = true
        return HttpResponse.json(thing, { status: 201 })
      }),
    )

    const { hook } = setup({ validate: () => "名称无效" })
    await waitFor(() => expect(hook.result.current.itemsQuery.data).toEqual([thing]))

    act(() => hook.result.current.submit({ preventDefault() {} }))

    expect(toast.error).toHaveBeenCalledWith("名称无效")
    expect(posted).toBe(false)
  })

  it("maps the entity into the form when editing and resets on cancel", async () => {
    const { hook } = setup()
    await waitFor(() => expect(hook.result.current.itemsQuery.data).toEqual([thing]))

    act(() => hook.result.current.startEdit(thing))
    expect(hook.result.current.editingId).toBe("t-1")
    expect(hook.result.current.form).toEqual({ name: "Alpha" })

    act(() => hook.result.current.setField("name", "Alpha v2"))
    act(() => hook.result.current.cancelEdit())
    expect(hook.result.current.editingId).toBeNull()
    expect(hook.result.current.form).toEqual({ name: "" })
  })

  it("updates the editing item and clears editing state", async () => {
    let requestBody: unknown = null
    server.use(
      http.put("/api/things/:id", async ({ request }) => {
        requestBody = await request.json()
        return HttpResponse.json(thing)
      }),
    )

    const { hook } = setup()
    await waitFor(() => expect(hook.result.current.itemsQuery.data).toEqual([thing]))

    act(() => hook.result.current.startEdit(thing))
    act(() => hook.result.current.setField("name", "Alpha v2"))
    act(() => hook.result.current.submit({ preventDefault() {} }))

    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("已更新"))
    expect(requestBody).toEqual({ name: "Alpha v2" })
    expect(hook.result.current.editingId).toBeNull()
    expect(hook.result.current.form).toEqual({ name: "" })
  })

  it("removes the row optimistically and closes the dialog only on success", async () => {
    let resolveDelete!: () => void
    const gate = new Promise<void>((resolve) => {
      resolveDelete = resolve
    })
    let deleted = false
    server.use(
      http.delete("/api/things/:id", async () => {
        await gate
        deleted = true
        return new HttpResponse(null, { status: 204 })
      }),
      http.get("/api/things", () => HttpResponse.json(deleted ? [] : [thing])),
    )

    const { hook } = setup()
    await waitFor(() => expect(hook.result.current.itemsQuery.data).toEqual([thing]))

    act(() => hook.result.current.requestRemove(thing))
    expect(hook.result.current.deleting).toEqual(thing)

    act(() => hook.result.current.confirmRemove())
    // 服务端尚未响应，行已被乐观移除，对话框保持打开
    await waitFor(() => expect(hook.result.current.itemsQuery.data).toEqual([]))
    expect(hook.result.current.deleting).toEqual(thing)

    await act(async () => resolveDelete())
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("已删除"))
    await waitFor(() => expect(hook.result.current.deleting).toBeNull())
  })

  it("passes the saved entity to onSaved and the deleted id to onDeleted", async () => {
    const onSaved = vi.fn()
    const onDeleted = vi.fn()
    server.use(
      http.put("/api/things/:id", () => HttpResponse.json({ id: "t-1", name: "Alpha v2" })),
      http.delete("/api/things/:id", () => new HttpResponse(null, { status: 204 })),
    )

    const { hook } = setup({ onSaved, onDeleted })
    await waitFor(() => expect(hook.result.current.itemsQuery.data).toEqual([thing]))

    act(() => hook.result.current.startEdit(thing))
    act(() => hook.result.current.setField("name", "Alpha v2"))
    act(() => hook.result.current.submit({ preventDefault() {} }))
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("已更新"))
    // 调用方拿到服务端返回实体，可写入详情缓存（talents/crm 迁移场景）
    expect(onSaved).toHaveBeenCalledWith({ id: "t-1", name: "Alpha v2" })

    act(() => hook.result.current.requestRemove(thing))
    act(() => hook.result.current.confirmRemove())
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("已删除"))
    expect(onDeleted).toHaveBeenCalledWith("t-1")
  })

  it("leaves non-list caches under the same key prefix untouched during optimistic delete", async () => {
    server.use(http.delete("/api/things/:id", () => new HttpResponse(null, { status: 204 })))

    const { queryClient, hook } = setup()
    await waitFor(() => expect(hook.result.current.itemsQuery.data).toEqual([thing]))

    // 同前缀下的详情缓存（如 ["things", "thing", "t-1"]），乐观删除不可误伤
    const detail = { id: "t-1", name: "Alpha", extra: true }
    queryClient.setQueryData(["things", "thing", "t-1"], detail)

    act(() => hook.result.current.requestRemove(thing))
    act(() => hook.result.current.confirmRemove())

    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("已删除"))
    expect(queryClient.getQueryData(["things", "thing", "t-1"])).toEqual(detail)
  })

  it("rolls back every cached list variant when delete fails", async () => {
    server.use(
      http.delete("/api/things/:id", () => HttpResponse.json({ code: "boom", message: "服务器忙" }, { status: 500 })),
      http.get("/api/things", ({ request }) => {
        const query = new URL(request.url).searchParams.get("query")
        return HttpResponse.json(query === "x" ? [thing, { id: "t-2", name: "Beta" }] : [thing])
      }),
    )

    const { queryClient, hook } = setup()
    await waitFor(() => expect(hook.result.current.itemsQuery.data).toEqual([thing]))

    // 再挂一个带 filters 的缓存条目，验证回滚按前缀覆盖所有变体
    act(() => hook.result.current.setFilters((current) => ({ ...current, query: "x" })))
    await waitFor(() => expect(hook.result.current.itemsQuery.data).toHaveLength(2))

    act(() => hook.result.current.requestRemove(thing))
    act(() => hook.result.current.confirmRemove())

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("服务器忙"))
    // 当前 filtered 视图回滚
    await waitFor(() => expect(hook.result.current.itemsQuery.data).toHaveLength(2))
    // 无 filters 的非活跃缓存条目也被回滚（invalidate 不会 refetch 非活跃查询）
    expect(queryClient.getQueryData(["things", {}])).toEqual([thing])
    // 失败不关对话框
    expect(hook.result.current.deleting).toEqual(thing)
  })
})

describe("normalizeErrorMessage", () => {
  it("uses the message of Error instances", () => {
    expect(normalizeErrorMessage(new Error("服务器忙"), "删除失败")).toBe("服务器忙")
  })

  it("falls back for non-Error rejections", () => {
    expect(normalizeErrorMessage("nope", "删除失败")).toBe("删除失败")
    expect(normalizeErrorMessage(undefined, "删除失败")).toBe("删除失败")
  })
})
