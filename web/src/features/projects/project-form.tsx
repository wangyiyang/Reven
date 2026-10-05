import type { FormEvent } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"

import type { ProjectFormValues } from "./project-form-model"

type ProjectFormProps = {
  values: ProjectFormValues
  editing: boolean
  busy: boolean
  onChange: (values: ProjectFormValues) => void
  onSubmit: () => void
  onCancel: () => void
}

const selectClassName = "h-10 w-full rounded-md border border-[var(--line)] bg-[var(--bg)] px-3 text-sm"

export function ProjectForm(props: ProjectFormProps) {
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    props.onSubmit()
  }

  return (
    <form className="space-y-4" onSubmit={submit}>
      <div className="space-y-2">
        <Label htmlFor="project-name">名称</Label>
        <Input
          id="project-name"
          onChange={(event) => props.onChange({ ...props.values, name: event.target.value })}
          required
          value={props.values.name}
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="project-goal">目标</Label>
        <Input
          id="project-goal"
          onChange={(event) => props.onChange({ ...props.values, goal: event.target.value })}
          value={props.values.goal}
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="project-status">状态</Label>
        <select
          aria-label="状态"
          className={selectClassName}
          id="project-status"
          onChange={(event) => props.onChange({ ...props.values, status: event.target.value })}
          value={props.values.status}
        >
          <option value="进行中">进行中</option>
          <option value="已暂停">已暂停</option>
          <option value="已完成">已完成</option>
        </select>
      </div>
      <div className="space-y-2">
        <Label htmlFor="project-department">部门</Label>
        <Input
          id="project-department"
          onChange={(event) => props.onChange({ ...props.values, department: event.target.value })}
          value={props.values.department}
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="project-due">截止日</Label>
        <Input
          id="project-due"
          onChange={(event) => props.onChange({ ...props.values, due_on: event.target.value })}
          type="date"
          value={props.values.due_on}
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="project-github">GitHub 仓库</Label>
        <Input
          id="project-github"
          onChange={(event) => props.onChange({ ...props.values, github_repo: event.target.value })}
          value={props.values.github_repo}
        />
      </div>
      <div className="flex gap-2">
        <Button disabled={props.busy} type="submit">{props.editing ? "保存修改" : "添加项目"}</Button>
        {props.editing ? (
          <Button onClick={props.onCancel} type="button" variant="ghost">取消编辑</Button>
        ) : null}
      </div>
    </form>
  )
}
