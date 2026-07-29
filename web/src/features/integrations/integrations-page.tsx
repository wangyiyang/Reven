import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { BookOpenText, RefreshCcw } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { apiRequest } from "@/lib/api"
import { IntegrationCard } from "./integration-card"
import { PROVIDERS, type Integration, type Provider } from "./types"

interface EgressResponse {
  available: boolean
  ip: string | null
}

interface SaveVariables {
  provider: Provider
  publicConfig: Record<string, string>
  secret?: Record<string, string>
}

export function IntegrationsPage() {
  const queryClient = useQueryClient()
  const integrations = useQuery({
    queryKey: ["integrations"],
    queryFn: () => apiRequest<Integration[]>("/integrations"),
  })
  const egress = useQuery({
    queryKey: ["egress-ip"],
    queryFn: () => apiRequest<EgressResponse>("/system/egress-ip"),
  })
  const mutation = useMutation({
    mutationFn: runIntegrationAction,
    onSuccess: async (result) => {
      await queryClient.invalidateQueries({ queryKey: ["integrations"] })
      toast.success(result.message)
    },
    onError: (error: Error) => toast.error(error.message),
  })

  const byProvider = new Map(integrations.data?.map((item) => [item.provider, item]))
  const busyAction = mutation.isPending ? `${mutation.variables.provider}:${mutation.variables.action}` : undefined

  return (
    <main className="page-enter mx-auto w-full max-w-6xl px-5 py-10 sm:px-8 lg:px-12 lg:py-14">
      <header className="mb-12 grid gap-7 border-b border-[var(--ink)] pb-9 lg:grid-cols-[1fr_22rem]">
        <div>
          <p className="section-kicker"><BookOpenText aria-hidden size={15} />系统装帧 / Integrations</p>
          <h1 className="font-display mt-4 max-w-3xl text-[clamp(2.7rem,7vw,6rem)] leading-[0.92] tracking-[-0.045em]">
            连接你的<br /><i className="text-[var(--red)]">出版流水线</i>
          </h1>
        </div>
        <div className="self-end text-sm leading-7 text-[var(--muted)]">
          <p>公共配置可以随时修改。密钥写入后只展示不可逆提示，不会返回到浏览器。</p>
          <Button className="mt-4" onClick={() => integrations.refetch()} size="sm" variant="ghost">
            <RefreshCcw aria-hidden size={14} />刷新连接状态
          </Button>
        </div>
      </header>

      {integrations.isError ? (
        <p className="border border-[var(--red)] bg-[var(--red-soft)] p-5 text-sm text-[var(--red)]" role="alert">
          无法读取集成配置：{integrations.error.message}
        </p>
      ) : (
        <section aria-busy={integrations.isLoading} aria-label="集成配置">
          {PROVIDERS.map((definition) => (
            <IntegrationCard
              busyAction={busyAction}
              definition={definition}
              egressIp={egress.data?.ip}
              integration={byProvider.get(definition.provider)}
              key={definition.provider}
              onBootstrap={() => mutation.mutate({ action: "bootstrap", provider: "notion" })}
              onDelete={(provider) => mutation.mutate({ action: "delete", provider: provider as Provider })}
              onReplace={(provider, publicConfig, secret) => mutation.mutate({
                action: "save",
                provider: provider as Provider,
                publicConfig,
                secret,
              })}
              onSave={(provider, publicConfig) => mutation.mutate({
                action: "save",
                provider: provider as Provider,
                publicConfig,
              })}
              onTest={(provider) => mutation.mutate({ action: "test", provider: provider as Provider })}
            />
          ))}
        </section>
      )}
    </main>
  )
}

type Action =
  | ({ action: "save" } & SaveVariables)
  | { action: "delete"; provider: Provider }
  | { action: "test"; provider: Provider }
  | { action: "bootstrap"; provider: "notion" }

async function runIntegrationAction(action: Action): Promise<{ message: string }> {
  if (action.action === "save") {
    const body = { public_config: action.publicConfig, ...(action.secret ? { secret: action.secret } : {}) }
    await apiRequest<Integration>(`/integrations/${action.provider}`, { method: "PUT", body: JSON.stringify(body) })
    return { message: "配置已保存" }
  }
  if (action.action === "delete") {
    await apiRequest<Integration>(`/integrations/${action.provider}/secret`, { method: "DELETE" })
    return { message: "密钥已删除" }
  }
  if (action.action === "test") {
    await apiRequest<Integration>(`/integrations/${action.provider}/test`, { method: "POST" })
    return { message: action.provider === "feishu" ? "测试消息已发送" : "连接测试已完成" }
  }
  await apiRequest<{ patched: boolean; properties: string[] }>("/integrations/notion/bootstrap-schema", { method: "POST" })
  return { message: "Notion 字段初始化完成" }
}
