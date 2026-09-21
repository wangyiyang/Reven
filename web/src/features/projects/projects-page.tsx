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
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { apiRequest } from "@/lib/api"
import { safeGithubUrl } from "@/lib/external-url"

type Project = {
  id: string
  name: string
  goal: string | null
  status: string
  department: string | null
  due_on: string | null
  github_repo: string | null
  notes: string | null
  created_at: string
  updated_at: string
}

type ProjectForm = {
  name: string
  goal: string
  status: string
  department: string
  due_on: string
  github_repo: string
  notes: string
}

const initialForm: ProjectForm = {
  name: "",
  goal: "",
  status: "进行中",
  department: "",
  due_on: "",
  github_repo: "",
  notes: "",
}

function emptyToNull(value: string) {
  return value.trim() ? value.trim() : null
}

const githubRepoPattern = /^(?:https:\/\/github\.com\/)?[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+(?:\.git)?\/?$/

function hasValidProjectLinks(form: ProjectForm) {
  const githubRepo = form.github_repo.trim()
  if (githubRepo && !githubRepoPattern.test(githubRepo)) return false
  return true
}

function toPayload(input: ProjectForm) {
  return {
    name: input.name,
    goal: emptyToNull(input.goal),
    status: input.status,
    department: emptyToNull(input.department),
    due_on: emptyToNull(input.due_on),
    github_repo: emptyToNull(input.github_repo),
    notes: emptyToNull(input.notes),
  }
}

export function ProjectsPage() {
  const queryClient = useQueryClient()
  const [form, setForm] = useState(initialForm)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [deleting, setDeleting] = useState<Project | null>(null)
  const [filters, setFilters] = useState({ status: "", query: "" })

  const projectsQuery = useQuery({
    queryKey: ["projects", filters],
    queryFn: () => {
      const params = new URLSearchParams()
      if (filters.status) params.set("status", filters.status)
      if (filters.query.trim()) params.set("query", filters.query.trim())
      const suffix = params.size ? `?${params.toString()}` : ""
      return apiRequest<Project[]>(`/projects${suffix}`)
    },
  })

  async function invalidateProjects() {
    await queryClient.invalidateQueries({ queryKey: ["projects"] })
  }

  const createMutation = useMutation({
    mutationFn: (input: ProjectForm) =>
      apiRequest<Project>("/projects", { method: "POST", body: JSON.stringify(toPayload(input)) }),
    onSuccess: async () => {
      setForm(initialForm)
      await invalidateProjects()
      toast.success("项目已添加")
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : "保存失败"),
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, input }: { id: string; input: ProjectForm }) =>
      apiRequest<Project>(`/projects/${id}`, { method: "PUT", body: JSON.stringify(toPayload(input)) }),
    onSuccess: async () => {
      setForm(initialForm)
      setEditingId(null)
      await invalidateProjects()
      toast.success("项目已更新")
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : "更新失败"),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => apiRequest(`/projects/${id}`, { method: "DELETE" }),
    onMutate: async (id: string) => {
      // 乐观删除：远端库延迟高，先移除行再给服务端对账
      await queryClient.cancelQueries({ queryKey: ["projects"] })
      const previous = queryClient.getQueriesData<Project[]>({ queryKey: ["projects"] })
      queryClient.setQueriesData<Project[]>({ queryKey: ["projects"] }, (old) => old?.filter((project) => project.id !== id))
      return { previous }
    },
    onSuccess: () => toast.success("项目已删除"),
    onError: (error, _id, context) => {
      context?.previous?.forEach(([key, data]) => queryClient.setQueryData(key, data))
      toast.error(error instanceof Error ? error.message : "删除失败")
    },
    onSettled: async () => {
      await invalidateProjects()
    },
  })

  function updateField<K extends keyof ProjectForm>(key: K, value: ProjectForm[K]) {
    setForm((current) => ({ ...current, [key]: value }))
  }

  function startEdit(project: Project) {
    setEditingId(project.id)
    setForm({
      name: project.name,
      goal: project.goal ?? "",
      status: project.status,
      department: project.department ?? "",
      due_on: project.due_on ?? "",
      github_repo: project.github_repo ?? "",
      notes: project.notes ?? "",
    })
  }

  function cancelEdit() {
    setEditingId(null)
    setForm(initialForm)
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!hasValidProjectLinks(form)) {
      toast.error("GitHub 仓库格式不正确")
      return
    }
    if (editingId) {
      updateMutation.mutate({ id: editingId, input: form })
      return
    }
    createMutation.mutate(form)
  }

  return (
    <main className="page-enter mx-auto w-full max-w-7xl space-y-6 px-5 py-10 sm:px-8 lg:px-12 lg:py-14">
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold text-[var(--ink)]">项目库</h1>
        <p className="text-sm text-[var(--muted)]">一人公司项目台账：目标、状态、截止日、GitHub 仓库链接。</p>
      </div>

      <Card>
        <CardHeader>
          <h2 className="text-lg font-medium text-[var(--ink)]">{editingId ? "编辑项目" : "添加项目"}</h2>
        </CardHeader>
        <CardContent>
          <form className="grid gap-4 md:grid-cols-4" onSubmit={onSubmit}>
            <div className="space-y-2">
              <Label htmlFor="project-name">名称</Label>
              <Input id="project-name" onChange={(event) => updateField("name", event.target.value)} required value={form.name} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="project-goal">目标</Label>
              <Input id="project-goal" onChange={(event) => updateField("goal", event.target.value)} value={form.goal} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="project-status">状态</Label>
              <select
                aria-label="状态"
                className="h-10 w-full rounded-md border border-[var(--line)] bg-[var(--bg)] px-3 text-sm"
                id="project-status"
                onChange={(event) => updateField("status", event.target.value)}
                value={form.status}
              >
                <option value="进行中">进行中</option>
                <option value="已暂停">已暂停</option>
                <option value="已完成">已完成</option>
              </select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="project-department">部门</Label>
              <Input id="project-department" onChange={(event) => updateField("department", event.target.value)} value={form.department} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="project-due">截止日</Label>
              <Input id="project-due" onChange={(event) => updateField("due_on", event.target.value)} type="date" value={form.due_on} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="project-github">GitHub 仓库</Label>
              <Input id="project-github" onChange={(event) => updateField("github_repo", event.target.value)} value={form.github_repo} />
            </div>
            <div className="flex items-end gap-2">
              <Button disabled={createMutation.isPending || updateMutation.isPending} type="submit">
                {editingId ? "保存修改" : "添加项目"}
              </Button>
              {editingId ? (
                <Button onClick={cancelEdit} type="button" variant="ghost">
                  取消编辑
                </Button>
              ) : null}
            </div>
          </form>
        </CardContent>
      </Card>

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
                onChange={(event) => setFilters((current) => ({ ...current, status: event.target.value }))}
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
                onChange={(event) => setFilters((current) => ({ ...current, query: event.target.value }))}
                placeholder="按名称、目标或部门搜索"
                value={filters.query}
              />
            </div>
          </div>
          <div className="grid gap-3 lg:hidden">
            {projectsQuery.data?.length === 0 ? (
              <p className="py-6 text-center text-sm text-[var(--muted)]">暂无项目，先添加一个。</p>
            ) : null}
            {(projectsQuery.data ?? []).map((project) => {
              const githubUrl = project.github_repo ? safeGithubUrl(project.github_repo) : null
              const meta = [project.department, project.due_on ? `截止 ${project.due_on}` : null].filter(Boolean).join(" · ")
              return (
                <article
                  aria-label={`${project.name} 移动摘要`}
                  className="rounded-lg border border-[var(--line)] p-4"
                  key={project.id}
                >
                  <div className="flex items-start justify-between gap-3">
                    <p className="min-w-0 font-semibold text-[var(--ink)]">{project.name}</p>
                    <Badge>{project.status}</Badge>
                  </div>
                  {project.goal ? <p className="mt-2 line-clamp-2 text-sm text-[var(--muted)]">{project.goal}</p> : null}
                  {meta ? <p className="mt-2 text-xs text-[var(--muted)]">{meta}</p> : null}
                  <div className="mt-3 flex items-center justify-between">
                    <div className="flex gap-3 text-xs">
                      {githubUrl ? (
                        <a className="text-[var(--signal)] underline underline-offset-2" href={githubUrl} rel="noreferrer" target="_blank">
                          GitHub
                        </a>
                      ) : null}
                    </div>
                    <div className="flex gap-1">
                      <Button aria-label={`编辑 ${project.name}`} onClick={() => startEdit(project)} size="sm" type="button" variant="ghost">
                        编辑
                      </Button>
                      <Button aria-label={`删除 ${project.name}`} onClick={() => setDeleting(project)} size="sm" type="button" variant="ghost">
                        删除
                      </Button>
                    </div>
                  </div>
                </article>
              )
            })}
          </div>
          <div className="hidden lg:block">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>名称</TableHead>
                <TableHead>状态</TableHead>
                <TableHead>部门</TableHead>
                <TableHead>截止日</TableHead>
                <TableHead>GitHub</TableHead>
                <TableHead>操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {projectsQuery.data?.length === 0 ? (
                <TableRow>
                  <TableCell className="py-10 text-center text-[var(--muted)]" colSpan={6}>
                    暂无项目，先添加一个。
                  </TableCell>
                </TableRow>
              ) : null}
              {(projectsQuery.data ?? []).map((project) => (
                <TableRow key={project.id}>
                  <TableCell>
                    <div className="font-medium text-[var(--ink)]">{project.name}</div>
                    {project.goal ? <div className="text-xs text-[var(--muted)]">{project.goal}</div> : null}
                  </TableCell>
                  <TableCell><Badge>{project.status}</Badge></TableCell>
                  <TableCell>{project.department ?? "—"}</TableCell>
                  <TableCell>{project.due_on ?? "—"}</TableCell>
                  <TableCell>
                    {(() => {
                      const githubUrl = project.github_repo ? safeGithubUrl(project.github_repo) : null
                      if (!githubUrl) return project.github_repo ?? "—"
                      return (
                        <a
                          className="text-[var(--signal)] underline underline-offset-2 hover:text-[var(--ink)]"
                          href={githubUrl}
                          rel="noreferrer"
                          target="_blank"
                        >
                          {project.github_repo}
                        </a>
                      )
                    })()}
                  </TableCell>
                  <TableCell>
                    <div className="flex gap-1">
                      <Button onClick={() => startEdit(project)} size="sm" type="button" variant="ghost">
                        编辑
                      </Button>
                      <Button
                        onClick={() => setDeleting(project)}
                        size="sm"
                        type="button"
                        variant="ghost"
                      >
                        删除
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          </div>
        </CardContent>
      </Card>
      <ConfirmDialog
        busy={deleteMutation.isPending}
        confirmLabel={`确认删除「${deleting?.name ?? ""}」`}
        description="删除后无法恢复，请确认这个项目已不再需要。"
        onClose={() => setDeleting(null)}
        onConfirm={() => {
          if (!deleting) return
          deleteMutation.mutate(deleting.id, { onSuccess: () => setDeleting(null) })
        }}
        open={deleting !== null}
        title="删除项目"
      />
    </main>
  )
}
