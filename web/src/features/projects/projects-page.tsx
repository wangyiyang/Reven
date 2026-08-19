import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import type { FormEvent } from "react"
import { useState } from "react"
import { toast } from "sonner"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { apiRequest } from "@/lib/api"

type Project = {
  id: string
  name: string
  goal: string | null
  status: string
  department: string | null
  due_on: string | null
  notion_url: string | null
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
  notion_url: string
  github_repo: string
  notes: string
}

const initialForm: ProjectForm = {
  name: "",
  goal: "",
  status: "进行中",
  department: "",
  due_on: "",
  notion_url: "",
  github_repo: "",
  notes: "",
}

function emptyToNull(value: string) {
  return value.trim() ? value.trim() : null
}

export function ProjectsPage() {
  const queryClient = useQueryClient()
  const [form, setForm] = useState(initialForm)

  const projectsQuery = useQuery({
    queryKey: ["projects"],
    queryFn: () => apiRequest<Project[]>("/projects"),
  })

  const createMutation = useMutation({
    mutationFn: (input: ProjectForm) =>
      apiRequest<Project>("/projects", {
        method: "POST",
        body: JSON.stringify({
          name: input.name,
          goal: emptyToNull(input.goal),
          status: input.status,
          department: emptyToNull(input.department),
          due_on: emptyToNull(input.due_on),
          notion_url: emptyToNull(input.notion_url),
          github_repo: emptyToNull(input.github_repo),
          notes: emptyToNull(input.notes),
        }),
      }),
    onSuccess: async () => {
      setForm(initialForm)
      await queryClient.invalidateQueries({ queryKey: ["projects"] })
      toast.success("项目已添加")
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : "保存失败"),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => apiRequest(`/projects/${id}`, { method: "DELETE" }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["projects"] })
      toast.success("项目已删除")
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : "删除失败"),
  })

  function updateField<K extends keyof ProjectForm>(key: K, value: ProjectForm[K]) {
    setForm((current) => ({ ...current, [key]: value }))
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    createMutation.mutate(form)
  }

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold text-[var(--ink)]">项目库</h1>
        <p className="text-sm text-[var(--muted)]">一人公司项目台账：目标、状态、截止日、GitHub 与 Notion 链接。</p>
      </div>

      <Card>
        <CardHeader>
          <h2 className="text-lg font-medium text-[var(--ink)]">添加项目</h2>
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
            <div className="space-y-2 md:col-span-2">
              <Label htmlFor="project-notion">Notion URL</Label>
              <Input id="project-notion" onChange={(event) => updateField("notion_url", event.target.value)} value={form.notion_url} />
            </div>
            <div className="flex items-end">
              <Button disabled={createMutation.isPending} type="submit">添加项目</Button>
            </div>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <h2 className="text-lg font-medium text-[var(--ink)]">项目列表</h2>
        </CardHeader>
        <CardContent>
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
              {(projectsQuery.data ?? []).map((project) => (
                <TableRow key={project.id}>
                  <TableCell>
                    <div className="font-medium text-[var(--ink)]">{project.name}</div>
                    {project.goal ? <div className="text-xs text-[var(--muted)]">{project.goal}</div> : null}
                  </TableCell>
                  <TableCell><Badge>{project.status}</Badge></TableCell>
                  <TableCell>{project.department ?? "—"}</TableCell>
                  <TableCell>{project.due_on ?? "—"}</TableCell>
                  <TableCell>{project.github_repo ?? "—"}</TableCell>
                  <TableCell>
                    <Button onClick={() => deleteMutation.mutate(project.id)} size="sm" type="button" variant="ghost">删除</Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  )
}
