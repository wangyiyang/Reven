import { useState } from "react"

import { ResponsiveList } from "@/components/responsive-list"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import { ConfirmDialog } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { safeGithubUrl } from "@/lib/external-url"
import { useResourceList } from "@/lib/use-resource-list"

import { ProjectFormDrawer } from "./project-form-drawer"
import {
  EMPTY_PROJECT_FORM,
  projectFormToPayload,
  projectToForm,
  validateProjectForm,
  type Project,
  type ProjectFormValues,
} from "./project-form-model"

function githubLink(project: Project, className: string, text: string) {
  const githubUrl = project.github_repo ? safeGithubUrl(project.github_repo) : null
  if (!githubUrl) return null
  return (
    <a className={className} href={githubUrl} rel="noreferrer" target="_blank">
      {text}
    </a>
  )
}

export function ProjectsPage() {
  const [creating, setCreating] = useState(false)
  const list = useResourceList<Project, ProjectFormValues>({
    key: "projects",
    path: "/projects",
    initialForm: EMPTY_PROJECT_FORM,
    initialFilters: { status: "", query: "" },
    toPayload: projectFormToPayload,
    toForm: projectToForm,
    validate: validateProjectForm,
    onSaved: () => setCreating(false),
    messages: {
      created: "项目已添加",
      updated: "项目已更新",
      deleted: "项目已删除",
      saveFailed: "保存失败",
      updateFailed: "更新失败",
      deleteFailed: "删除失败",
    },
  })
  const { filters } = list
  const editing = list.editingId
    ? (list.itemsQuery.data ?? []).find((item) => item.id === list.editingId) ?? null
    : null

  function closeDrawer() {
    if (list.editingId) {
      list.cancelEdit()
      return
    }
    setCreating(false)
  }

  return (
    <main className="page-enter mx-auto w-full max-w-7xl space-y-6 px-5 py-10 sm:px-8 lg:px-12 lg:py-14">
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-2">
          <h1 className="text-2xl font-semibold text-[var(--ink)]">项目库</h1>
          <p className="text-sm text-[var(--muted)]">一人公司项目台账：目标、状态、截止日、GitHub 仓库链接。</p>
        </div>
        <Button onClick={() => setCreating(true)}>新建项目</Button>
      </div>

      <Card>
        <CardHeader>
          <h2 className="text-lg font-medium text-[var(--ink)]">项目列表</h2>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-end gap-3">
            <div className="space-y-2">
              <Label htmlFor="projects-filter-status">状态筛选</Label>
              <select
                aria-label="状态筛选"
                className="h-10 w-full rounded-md border border-[var(--line)] bg-[var(--bg)] px-3 text-sm"
                id="projects-filter-status"
                onChange={(event) => list.setFilters((current) => ({ ...current, status: event.target.value }))}
                value={filters.status}
              >
                <option value="">全部</option>
                <option value="进行中">进行中</option>
                <option value="已暂停">已暂停</option>
                <option value="已完成">已完成</option>
              </select>
            </div>
            <div className="min-w-56 flex-1 space-y-2">
              <Label htmlFor="projects-filter-query">搜索</Label>
              <Input
                aria-label="搜索项目"
                id="projects-filter-query"
                onChange={(event) => list.setFilters((current) => ({ ...current, query: event.target.value }))}
                placeholder="按名称、目标或部门搜索"
                value={filters.query}
              />
            </div>
          </div>
          <ResponsiveList
            actions={[
              { label: "编辑", ariaLabel: (project) => `编辑 ${project.name}`, onClick: list.startEdit },
              { label: "删除", ariaLabel: (project) => `删除 ${project.name}`, onClick: list.requestRemove },
            ]}
            card={(project) => {
              const meta = [project.department, project.due_on ? `截止 ${project.due_on}` : null].filter(Boolean).join(" · ")
              return {
                title: project.name,
                status: <Badge>{project.status}</Badge>,
                body: project.goal ? <p className="mt-2 line-clamp-2 text-sm text-[var(--muted)]">{project.goal}</p> : null,
                meta: meta ? <p className="mt-2 text-xs text-[var(--muted)]">{meta}</p> : null,
                links: githubLink(project, "text-[var(--signal)] underline underline-offset-2", "GitHub"),
              }
            }}
            cardLabel={(project) => `${project.name} 移动摘要`}
            columns={[
              {
                header: "名称",
                cell: (project) => (
                  <>
                    <div className="font-medium text-[var(--ink)]">{project.name}</div>
                    {project.goal ? <div className="text-xs text-[var(--muted)]">{project.goal}</div> : null}
                  </>
                ),
              },
              { header: "状态", cell: (project) => <Badge>{project.status}</Badge> },
              { header: "部门", cell: (project) => project.department ?? "—" },
              { header: "截止日", cell: (project) => project.due_on ?? "—" },
              {
                header: "GitHub",
                cell: (project) =>
                  githubLink(
                    project,
                    "text-[var(--signal)] underline underline-offset-2 hover:text-[var(--ink)]",
                    project.github_repo ?? "",
                  ) ??
                  project.github_repo ??
                  "—",
              },
            ]}
            emptyText="暂无项目，先添加一个。"
            items={list.itemsQuery.data}
            keyOf={(project) => project.id}
          />
        </CardContent>
      </Card>
      <ProjectFormDrawer
        busy={list.isSaving}
        editing={editing}
        onChange={list.setForm}
        onClose={closeDrawer}
        onSubmit={list.submit}
        open={creating || editing !== null}
        values={list.form}
      />
      <ConfirmDialog
        busy={list.isRemoving}
        confirmLabel={`确认删除「${list.deleting?.name ?? ""}」`}
        description="删除后无法恢复，请确认这个项目已不再需要。"
        onClose={list.cancelRemove}
        onConfirm={list.confirmRemove}
        open={list.deleting !== null}
        title="删除项目"
      />
    </main>
  )
}
