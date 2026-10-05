import { Drawer } from "@/components/ui/drawer"

import { SopForm } from "./sop-form"
import type { SopFormValues } from "./sop-form-model"

type SopFormDrawerProps = {
  open: boolean
  editing: boolean
  values: SopFormValues
  busy: boolean
  onChange: (values: SopFormValues) => void
  onSubmit: () => void
  onClose: () => void
}

export function SopFormDrawer(props: SopFormDrawerProps) {
  return (
    <Drawer onClose={props.onClose} open={props.open} title={props.editing ? "编辑 SOP" : "新建 SOP"}>
      <SopForm
        busy={props.busy}
        editing={props.editing}
        onCancel={props.onClose}
        onChange={props.onChange}
        onSubmit={props.onSubmit}
        values={props.values}
      />
    </Drawer>
  )
}
