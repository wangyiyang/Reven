import { Drawer } from "@/components/ui/drawer"

import { CustomerForm } from "./customer-form"
import type { CustomerFormValues } from "./customer-form-model"

type CustomerFormDrawerProps = {
  open: boolean
  editing: boolean
  values: CustomerFormValues
  busy: boolean
  onChange: (values: CustomerFormValues) => void
  onSubmit: () => void
  onClose: () => void
}

export function CustomerFormDrawer(props: CustomerFormDrawerProps) {
  if (!props.open) return null
  return (
    <Drawer onClose={props.onClose} open title={props.editing ? "编辑客户" : "新建客户"}>
      <CustomerForm
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
