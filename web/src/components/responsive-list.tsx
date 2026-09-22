import type { ReactNode } from "react"

import { Button } from "@/components/ui/button"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"

export type ResponsiveListColumn<T> = {
  header: ReactNode
  cell: (item: T) => ReactNode
  /** 同时作用于桌面表格的 th/td（如金额列 text-right、标签列 max-w-64） */
  className?: string
}

export type ResponsiveListAction<T> = {
  label: string
  ariaLabel: (item: T) => string
  onClick: (item: T) => void
  /** 按钮变体，默认 ghost；主操作（如确认收款）可用 outline */
  variant?: "ghost" | "outline"
}

export type ResponsiveListCard = {
  title: ReactNode
  status?: ReactNode
  body?: ReactNode
  meta?: ReactNode
  links?: ReactNode
}

export type ResponsiveListProps<T> = {
  items: T[] | undefined
  keyOf: (item: T) => string
  emptyText: string
  columns: ResponsiveListColumn<T>[]
  card: (item: T) => ResponsiveListCard
  /** 移动卡片 article 的 aria-label（如 `${name} 移动摘要`） */
  cardLabel: (item: T) => string
  /** 两个视口共用同一组 action 定义，按钮 aria-label 对等 */
  actions: ResponsiveListAction<T>[]
}

export function ResponsiveList<T>({ items, keyOf, emptyText, columns, card, cardLabel, actions }: ResponsiveListProps<T>) {
  return (
    <>
      <div className="grid gap-3 lg:hidden">
        {items?.length === 0 ? <p className="py-6 text-center text-sm text-[var(--muted)]">{emptyText}</p> : null}
        {(items ?? []).map((item) => {
          const content = card(item)
          return (
            <article aria-label={cardLabel(item)} className="rounded-lg border border-[var(--line)] p-4" key={keyOf(item)}>
              <div className="flex items-start justify-between gap-3">
                <p className="min-w-0 font-semibold text-[var(--ink)]">{content.title}</p>
                {content.status}
              </div>
              {content.body}
              {content.meta}
              <div className="mt-3 flex items-center justify-between">
                <div className="flex gap-3 text-xs">{content.links}</div>
                <div className="flex gap-1">{renderActions(actions, item)}</div>
              </div>
            </article>
          )
        })}
      </div>
      <div className="hidden lg:block">
        <Table>
          <TableHeader>
            <TableRow>
              {columns.map((column, index) => (
                <TableHead className={column.className} key={index}>{column.header}</TableHead>
              ))}
              <TableHead>操作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items?.length === 0 ? (
              <TableRow>
                <TableCell className="py-10 text-center text-[var(--muted)]" colSpan={columns.length + 1}>
                  {emptyText}
                </TableCell>
              </TableRow>
            ) : null}
            {(items ?? []).map((item) => (
              <TableRow key={keyOf(item)}>
                {columns.map((column, index) => (
                  <TableCell className={column.className} key={index}>{column.cell(item)}</TableCell>
                ))}
                <TableCell>
                  <div className="flex gap-1">{renderActions(actions, item)}</div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </>
  )
}

function renderActions<T>(actions: ResponsiveListAction<T>[], item: T) {
  return actions.map((action) => (
    <Button
      aria-label={action.ariaLabel(item)}
      key={action.label}
      onClick={() => action.onClick(item)}
      size="sm"
      type="button"
      variant={action.variant ?? "ghost"}
    >
      {action.label}
    </Button>
  ))
}
