import { useMutation, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"

import { createCustomer, crmKeys, deleteCustomer, updateCustomer } from "./crm-api"
import type { CustomerInput } from "./types"

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "请求失败"
}

export function useCreateCustomer(onSaved: () => void) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: createCustomer,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: crmKeys.customers })
      onSaved()
      toast.success("客户已添加")
    },
    onError: (error) => toast.error(errorMessage(error)),
  })
}

export function useUpdateCustomer(onSaved: () => void) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ customerId, input }: { customerId: string; input: CustomerInput }) =>
      updateCustomer(customerId, input),
    onSuccess: async (customer) => {
      queryClient.setQueryData(crmKeys.customer(customer.id), customer)
      await queryClient.invalidateQueries({ queryKey: crmKeys.customers })
      onSaved()
      toast.success("客户已更新")
    },
    onError: (error) => toast.error(errorMessage(error)),
  })
}

export function useDeleteCustomer(onDeleted: () => void) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: deleteCustomer,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: crmKeys.customers })
      onDeleted()
      toast.success("客户已删除")
    },
    onError: (error) => toast.error(errorMessage(error)),
  })
}
