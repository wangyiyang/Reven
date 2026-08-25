import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useCallback, useRef, useState } from "react"
import { toast } from "sonner"

import { apiRequest } from "@/lib/api"
import {
  fetchIntegrations,
  fetchLatestRssRun,
  runIntegrationAction,
  type EgressResponse,
  type IntegrationAction,
} from "./integration-api"
import type { Integration, Provider } from "./types"

export function useIntegrationsController() {
  const queryClient = useQueryClient()
  const actionLocked = useRef(false)
  const [isActionLocked, setIsActionLocked] = useState(false)
  const integrations = useQuery({ queryKey: ["integrations"], queryFn: fetchIntegrations })
  const egress = useQuery({
    queryKey: ["egress-ip"],
    queryFn: () => apiRequest<EgressResponse>("/system/egress-ip"),
    enabled: integrations.isSuccess,
  })
  const latestRun = useQuery({
    queryKey: ["rss-latest-run"],
    queryFn: fetchLatestRssRun,
    enabled: integrations.isSuccess,
  })
  const mutation = useMutation({
    mutationFn: runIntegrationAction,
    onSuccess: async (result) => {
      await queryClient.invalidateQueries({ queryKey: ["integrations"] })
      toast.success(result.message)
    },
    onError: (error: Error) => toast.error(error.message),
  })
  const execute = useCallback(async (action: IntegrationAction): Promise<boolean> => {
    if (actionLocked.current) return false
    actionLocked.current = true
    setIsActionLocked(true)
    try {
      await mutation.mutateAsync(action)
      return true
    } catch {
      return false
    } finally {
      actionLocked.current = false
      setIsActionLocked(false)
    }
  }, [mutation])
  return {
    integrations,
    egress,
    latestRun,
    execute,
    isActionLocked,
    busyAction: mutation.isPending ? `${mutation.variables.provider}:${mutation.variables.action}` : undefined,
    byProvider: new Map<Provider, Integration>(integrations.data?.map((item) => [item.provider, item])),
  }
}
