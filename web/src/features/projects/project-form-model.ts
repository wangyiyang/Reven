export type Project = {
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

export type ProjectFormValues = {
  name: string
  goal: string
  status: string
  department: string
  due_on: string
  github_repo: string
  notes: string
}

export const EMPTY_PROJECT_FORM: ProjectFormValues = {
  name: "",
  goal: "",
  status: "进行中",
  department: "",
  due_on: "",
  github_repo: "",
  notes: "",
}

const githubRepoPattern = /^(?:https:\/\/github\.com\/)?[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+(?:\.git)?\/?$/

export function projectToForm(project: Project): ProjectFormValues {
  return {
    name: project.name,
    goal: project.goal ?? "",
    status: project.status,
    department: project.department ?? "",
    due_on: project.due_on ?? "",
    github_repo: project.github_repo ?? "",
    notes: project.notes ?? "",
  }
}

export function projectFormToPayload(values: ProjectFormValues) {
  return {
    name: values.name,
    goal: emptyToNull(values.goal),
    status: values.status,
    department: emptyToNull(values.department),
    due_on: emptyToNull(values.due_on),
    github_repo: emptyToNull(values.github_repo),
    notes: emptyToNull(values.notes),
  }
}

export function validateProjectForm(values: ProjectFormValues): string | null {
  const githubRepo = values.github_repo.trim()
  if (githubRepo && !githubRepoPattern.test(githubRepo)) return "GitHub 仓库格式不正确"
  return null
}

function emptyToNull(value: string) {
  return value.trim() ? value.trim() : null
}
