import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useCallback, useRef } from "react"
import { toast } from "sonner"

import { apiRequest } from "@/lib/api"
import {
  fetchIntegrations,
  runIntegrationAction,
  type EgressResponse,
  type IntegrationAction,
} from "./integration-api"
import type { Integration, Provider } from "./types"

export function useIntegrationsController() {
  const queryClient = useQueryClient()
  const actionLocked = useRef(false)
  const integrations = useQuery({ queryKey: ["integrations"], queryFn: fetchIntegrations })
  const egress = useQuery({
    queryKey: ["egress-ip"],
    queryFn: () => apiRequest<EgressResponse>("/system/egress-ip"),
    enabled: integrations.isSuccess,
  })
  const mutation = useMutation({
    mutationFn: runIntegrationAction,
    onSuccess: async (result) => {
      await queryClient.invalidateQueries({ queryKey: ["integrations"] })
      toast.success(result.message)
    },
    onError: (error: Error) => toast.error(error.message),
    onSettled: () => { actionLocked.current = false },
  })
  const execute = useCallback((action: IntegrationAction) => {
    if (actionLocked.current) return
    actionLocked.current = true
    mutation.mutate(action)
  }, [mutation])
  return {
    integrations,
    egress,
    execute,
    busyAction: mutation.isPending ? `${mutation.variables.provider}:${mutation.variables.action}` : undefined,
    byProvider: new Map<Provider, Integration>(integrations.data?.map((item) => [item.provider, item])),
  }
}
