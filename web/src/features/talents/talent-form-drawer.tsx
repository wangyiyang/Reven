import { Drawer } from "@/components/ui/drawer"

import { TalentForm } from "./talent-form"
import type { TalentFormValues } from "./talent-form-model"

type TalentFormDrawerProps = {
  open: boolean
  form: TalentFormValues
  tagSuggestions: string[]
  busy: boolean
  onChange: (form: TalentFormValues) => void
  onSubmit: () => void
  onClose: () => void
}

export function TalentFormDrawer(props: TalentFormDrawerProps) {
  if (!props.open) return null
  return (
    <Drawer onClose={props.onClose} open title="新建人才">
      <TalentForm
        busy={props.busy}
        editing={false}
        onCancel={props.onClose}
        onChange={props.onChange}
        onSubmit={props.onSubmit}
        tagSuggestions={props.tagSuggestions}
        values={props.form}
      />
    </Drawer>
  )
}
