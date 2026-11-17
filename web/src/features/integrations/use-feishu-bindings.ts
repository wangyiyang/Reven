import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useCallback, useState } from "react"
import { toast } from "sonner"

import {
  fetchFeishuBindings,
  runFeishuBindingAction,
  testFeishuBinding,
  type FeishuBindingAction,
} from "./feishu-bindings-api"
import type { BindingTestResult } from "./types"

/**
 * 飞书多维表格绑定的 server state：列表查询 + 变更 mutation（默认按前缀失效）+ 测试探针。
 * 测试结果存卡片本地 state（按绑定 id 索引），不落缓存；配置变更/删除后旧结果即失效并清除。
 */
export function useFeishuBindings() {
  const queryClient = useQueryClient()
  const bindings = useQuery({ queryKey: ["feishu-bindings"], queryFn: fetchFeishuBindings })
  const [tests, setTests] = useState<Record<string, BindingTestResult>>({})
  const mutation = useMutation({
    mutationFn: runFeishuBindingAction,
    onSuccess: async (result, action) => {
      await queryClient.invalidateQueries({ queryKey: ["feishu-bindings"] })
      // 更新/删除后该绑定上次的测试结果测的是旧配置（或已不存在的绑定），一并清除
      if (action.action === "update" || action.action === "delete") {
        setTests((current) => omitKey(current, action.id))
      }
      toast.success(result.message)
    },
    onError: (error: Error) => toast.error(error.message),
  })
  const testMutation = useMutation({
    mutationFn: testFeishuBinding,
    onSuccess: (result, id) => {
      setTests((current) => ({ ...current, [id]: result }))
      // 探针失败不是请求异常：响应已带分阶段结果，toast 摘要 + 行内面板展示细节
      if (result.success) toast.success("绑定测试通过")
      else toast.error(result.message ?? "绑定测试未通过，详见绑定列表中的分阶段结果")
    },
    onError: (error: Error, id) => {
      setTests((current) => omitKey(current, id))
      toast.error(error.message)
    },
  })
  const execute = useCallback(async (action: FeishuBindingAction): Promise<boolean> => {
    try {
      await mutation.mutateAsync(action)
      return true
    } catch {
      return false
    }
  }, [mutation])

  return {
    bindings,
    tests,
    execute,
    busy: mutation.isPending,
    test: testMutation.mutate,
    testingId: testMutation.isPending ? testMutation.variables ?? null : null,
  }
}

function omitKey<T>(record: Record<string, T>, key: string): Record<string, T> {
  const next = { ...record }
  delete next[key]
  return next
}
