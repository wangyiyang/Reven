import { BookOpenText, RefreshCcw } from "lucide-react"

import { Button } from "@/components/ui/button"
import { IntegrationCard } from "./integration-card"
import { IntegrationsLoading } from "./integrations-loading"
import { PROVIDERS } from "./types"
import { useIntegrationsController } from "./use-integrations-controller"

export function IntegrationsPage() {
  const controller = useIntegrationsController()
  return (
    <main className="page-enter mx-auto w-full max-w-6xl px-5 py-10 sm:px-8 lg:px-12 lg:py-14">
      <PageHeader onRefresh={() => controller.integrations.refetch()} />
      {controller.integrations.isLoading && <IntegrationsLoading />}
      {controller.integrations.isError && (
        <div className="border border-[var(--red)] bg-[var(--red-soft)] p-5 text-sm text-[var(--red)]" role="alert">
          <p>无法读取集成配置：{controller.integrations.error.message}</p>
          <Button className="mt-4" onClick={() => controller.integrations.refetch()} variant="outline">重新读取</Button>
        </div>
      )}
      {controller.integrations.isSuccess && (
        <section aria-label="集成配置">
          {PROVIDERS.map((definition) => (
            <IntegrationCard
              busyAction={controller.busyAction}
              definition={definition}
              egressIp={controller.egress.data?.ip}
              integration={controller.byProvider.get(definition.provider)}
              key={definition.provider}
              onBootstrap={() => controller.execute({ action: "bootstrap", provider: "notion" })}
              onDelete={(provider) => controller.execute({ action: "delete", provider })}
              onReplace={(provider, publicConfig, secret) => controller.execute({ action: "save", provider, publicConfig, secret })}
              onSave={(provider, publicConfig) => controller.execute({ action: "save", provider, publicConfig })}
              onTest={(provider) => controller.execute({ action: "test", provider })}
            />
          ))}
        </section>
      )}
    </main>
  )
}

function PageHeader({ onRefresh }: { onRefresh: () => void }) {
  return (
    <header className="mb-12 grid gap-7 border-b border-[var(--ink)] pb-9 lg:grid-cols-[1fr_22rem]">
      <div>
        <p className="section-kicker"><BookOpenText aria-hidden size={15} />系统装帧 / Integrations</p>
        <h1 className="font-display mt-4 max-w-3xl text-[clamp(2.7rem,7vw,6rem)] leading-[0.92] tracking-[-0.045em]">连接你的<br /><i className="text-[var(--red)]">出版流水线</i></h1>
      </div>
      <div className="self-end text-sm leading-7 text-[var(--muted)]">
        <p>公共配置可以随时修改。密钥写入后只展示不可逆提示，不会返回到浏览器。</p>
        <Button className="mt-4" onClick={onRefresh} size="sm" variant="ghost"><RefreshCcw aria-hidden size={14} />刷新连接状态</Button>
      </div>
    </header>
  )
}
