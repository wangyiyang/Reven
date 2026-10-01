import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useCallback, useRef, useState } from "react"
import { toast } from "sonner"

import {
  fetchIntegrations,
  fetchLatestRssRun,
  runIntegrationAction,
  type IntegrationAction,
} from "./integration-api"
import type { Integration, ModelTestState, Provider, ProviderController } from "./types"

export function useIntegrationsController() {
  const queryClient = useQueryClient()
  const actionLocked = useRef(false)
  const [isActionLocked, setIsActionLocked] = useState(false)
  const [modelTests, setModelTests] = useState<Record<string, ModelTestState>>({})
  const integrations = useQuery({ queryKey: ["integrations"], queryFn: fetchIntegrations })
  const latestRun = useQuery({
    queryKey: ["rss-latest-run"],
    queryFn: fetchLatestRssRun,
    enabled: integrations.isSuccess,
  })
  const mutation = useMutation({
    mutationFn: runIntegrationAction,
    onSuccess: async (result, action) => {
      if (action.action === "test" && result.integration) {
        // 测试连接：以响应局部更新缓存，避免整表 refetch 清空卡片未保存的暂存（#179）
        const updated = result.integration
        queryClient.setQueryData<Integration[]>(["integrations"], (current) =>
          (current ?? []).map((item) => (item.provider === updated.provider ? updated : item)))
      } else if (action.action !== "test-model") {
        // test-model 为只读探测：不改服务端状态，完全不触碰缓存
        await queryClient.invalidateQueries({ queryKey: ["integrations"] })
      }
      if (result.modelTest !== undefined) {
        const test = result.modelTest
        setModelTests((current) => ({
          ...current,
          [test.ref]: {
            status: test.success ? "ok" : "failed",
            message: test.message,
            latencyMs: test.latency_ms,
          },
        }))
        if (!test.success) {
          toast.error(result.message)
          return
        }
      }
      if (result.ok === false) {
        toast.error(result.message)
        return
      }
      toast.success(result.message)
    },
    onError: (error: Error) => {
      // 失败的动作未改变服务端状态：仅提示，不 refetch（整表刷新会清空卡片暂存，#179）
      toast.error(error.message)
    },
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

  const pendingAction = mutation.isPending ? mutation.variables : undefined
  const forProvider = useCallback((provider: Provider): ProviderController => ({
    state: {
      integration: integrations.data?.find((item) => item.provider === provider),
      runHealth: latestRun.data,
      disabled: isActionLocked,
      busy: pendingAction && pendingAction.provider === provider ? pendingAction.action : null,
      testingModelRef:
        pendingAction && pendingAction.provider === provider && pendingAction.action === "test-model"
          ? pendingAction.ref
          : null,
      modelTests,
    },
    actions: {
      save: (publicConfig, secret) => execute({ action: "save", provider, publicConfig, ...(secret ? { secret } : {}) }),
      replace: (publicConfig, secret) => void execute({ action: "save", provider, publicConfig, secret }),
      remove: () => execute({ action: "delete", provider }),
      test: () => void execute({ action: "test", provider }),
      setDefaultModel: (ref) => void execute({ action: "set-default-model", provider, ref }),
      testModel: (ref) => void execute({ action: "test-model", provider, ref }),
    },
  }), [integrations.data, latestRun.data, isActionLocked, pendingAction, modelTests, execute])

  return { integrations, isActionLocked, forProvider }
}
