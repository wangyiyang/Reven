import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"
import { toast } from "sonner"

import { ConfirmDialog } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { ApiError } from "@/lib/api"

import { confirmEntry, type FinanceEntry } from "./finance-api"
import { formatMoney, todayShanghai } from "./finance-utils"

type ConfirmSettleDialogProps = {
  entry: FinanceEntry | null
  onClose: () => void
}

export function ConfirmSettleDialog({ entry, onClose }: ConfirmSettleDialogProps) {
  if (!entry) return null
  return <ConfirmSettleDialogInner entry={entry} onClose={onClose} />
}

function ConfirmSettleDialogInner({ entry, onClose }: { entry: FinanceEntry; onClose: () => void }) {
  const queryClient = useQueryClient()
  const [occurredOn, setOccurredOn] = useState(todayShanghai)
  const actionLabel = entry.status === "应收" ? "确认收款" : "确认付款"

  const mutation = useMutation({
    mutationFn: () => confirmEntry(entry.id, occurredOn),
    onSuccess: async () => {
      toast.success(`${actionLabel}成功`)
      await queryClient.invalidateQueries({ queryKey: ["finance"] })
      onClose()
    },
    onError: async (error) => {
      if (error instanceof ApiError && error.status === 409) {
        toast.error("该款项已确认，请刷新查看")
        await queryClient.invalidateQueries({ queryKey: ["finance"] })
        onClose()
        return
      }
      toast.error(error instanceof Error ? error.message : `${actionLabel}失败，请重试`)
    },
  })

  function submit() {
    if (!occurredOn) {
      toast.error("请选择实际收付日期")
      return
    }
    mutation.mutate()
  }

  return (
    <ConfirmDialog
      busy={mutation.isPending}
      confirmLabel={actionLabel}
      description={`${entry.name} · ${formatMoney(entry.amount_cents)}。确认后按实际收付日期计入流水与汇总。`}
      onClose={onClose}
      onConfirm={submit}
      open
      title={actionLabel}
      tone="primary"
    >
      <div className="space-y-2">
        <Label htmlFor="confirm-settle-date">实际收付日期</Label>
        <Input
          id="confirm-settle-date"
          onChange={(event) => setOccurredOn(event.target.value)}
          type="date"
          value={occurredOn}
        />
      </div>
    </ConfirmDialog>
  )
}
