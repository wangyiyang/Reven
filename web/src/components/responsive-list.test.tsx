import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { Badge } from "@/components/ui/badge"

import { ResponsiveList } from "./responsive-list"
import type { ResponsiveListAction, ResponsiveListColumn } from "./responsive-list"

type Row = { id: string; name: string; status: string; owner: string | null }

const rows: Row[] = [
  { id: "r-1", name: "Alpha", status: "进行中", owner: "甲" },
  { id: "r-2", name: "Beta", status: "已完成", owner: null },
]

const columns: ResponsiveListColumn<Row>[] = [
  { header: "名称", cell: (row) => row.name },
  { header: "负责人", cell: (row) => row.owner ?? "—" },
]

// null 表示加载中（items 为 undefined）
function renderList(items: Row[] | null = rows) {
  const edit = vi.fn()
  const remove = vi.fn()
  const actions: ResponsiveListAction<Row>[] = [
    { label: "编辑", ariaLabel: (row) => `编辑 ${row.name}`, onClick: edit },
    { label: "删除", ariaLabel: (row) => `删除 ${row.name}`, onClick: remove },
  ]
  render(
    <ResponsiveList
      actions={actions}
      card={(row) => ({
        title: row.name,
        status: <Badge>{row.status}</Badge>,
        meta: row.owner ? <p className="mt-2 text-xs">{row.owner}</p> : null,
      })}
      cardLabel={(row) => `${row.name} 移动摘要`}
      columns={columns}
      emptyText="暂无数据。"
      items={items ?? undefined}
      keyOf={(row) => row.id}
    />,
  )
  return { edit, remove }
}

describe("ResponsiveList", () => {
  it("renders every item in both the mobile cards and the desktop table", () => {
    renderList()

    // 同一数据两个视口各渲染一次
    expect(screen.getAllByText("Alpha")).toHaveLength(2)
    expect(screen.getAllByText("Beta")).toHaveLength(2)

    const card = screen.getByRole("article", { name: "Alpha 移动摘要" })
    expect(card).toHaveTextContent("进行中")
    expect(card).toHaveTextContent("甲")

    expect(screen.getByRole("columnheader", { name: "名称" })).toBeInTheDocument()
    expect(screen.getByRole("columnheader", { name: "负责人" })).toBeInTheDocument()
    expect(screen.getByRole("columnheader", { name: "操作" })).toBeInTheDocument()
    // 桌面行渲染空值兜底
    expect(screen.getByRole("cell", { name: "—" })).toBeInTheDocument()
  })

  it("shows the empty text in both viewports, spanning all table columns", () => {
    renderList([])

    expect(screen.getAllByText("暂无数据。")).toHaveLength(2)
    const cell = screen.getByRole("cell", { name: "暂无数据。" })
    expect(cell).toHaveAttribute("colspan", String(columns.length + 1))
  })

  it("renders no empty state and no cards while items are still loading", () => {
    renderList(null)

    expect(screen.queryByText("暂无数据。")).not.toBeInTheDocument()
    expect(screen.queryByRole("article")).not.toBeInTheDocument()
  })

  it("gives actions identical aria-labels in both viewports and routes clicks", async () => {
    const { edit, remove } = renderList()

    // aria-label 对等：移动卡片与桌面表格命中同一组带标签按钮
    expect(screen.getAllByRole("button", { name: "编辑 Alpha" })).toHaveLength(2)
    expect(screen.getAllByRole("button", { name: "删除 Beta" })).toHaveLength(2)

    await userEvent.click(screen.getAllByRole("button", { name: "编辑 Alpha" })[0])
    expect(edit).toHaveBeenCalledWith(rows[0])

    await userEvent.click(screen.getAllByRole("button", { name: "删除 Beta" })[1])
    expect(remove).toHaveBeenCalledWith(rows[1])
  })
})
