import { Skeleton } from "@/components/ui/skeleton"

export function IntegrationsLoading() {
  return (
    <section aria-busy="true" aria-label="正在读取集成配置">
      {[0, 1, 2, 3].map((item) => (
        <div className="mb-6 rounded-lg border border-[var(--line)] p-6" key={item}>
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="space-y-3">
              <Skeleton className="h-6 w-40" />
              <Skeleton className="h-4 w-full max-w-xl" />
            </div>
            <Skeleton className="h-7 w-20" />
          </div>
          <div className="mt-8 grid gap-6 lg:grid-cols-2">
            <Skeleton className="h-14 w-full" />
            <Skeleton className="h-14 w-full" />
          </div>
        </div>
      ))}
    </section>
  )
}
