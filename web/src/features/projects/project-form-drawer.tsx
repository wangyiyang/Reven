import { Drawer } from "@/components/ui/drawer"

import { ProjectForm } from "./project-form"
import type { Project, ProjectFormValues } from "./project-form-model"

type ProjectFormDrawerProps = {
  open: boolean
  editing: Project | null
  values: ProjectFormValues
  busy: boolean
  onChange: (values: ProjectFormValues) => void
  onSubmit: () => void
  onClose: () => void
}

export function ProjectFormDrawer(props: ProjectFormDrawerProps) {
  if (!props.open) return null
  return (
    <Drawer onClose={props.onClose} open title={props.editing ? "编辑项目" : "新建项目"}>
      <ProjectForm
        busy={props.busy}
        editing={props.editing !== null}
        onCancel={props.onClose}
        onChange={props.onChange}
        onSubmit={props.onSubmit}
        values={props.values}
      />
    </Drawer>
  )
}
