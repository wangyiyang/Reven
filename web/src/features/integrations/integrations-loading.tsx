import { Skeleton } from "@/components/ui/skeleton"

export function IntegrationsLoading() {
  return (
    <section aria-busy="true" aria-label="正在读取集成配置">
      {[0, 1, 2, 3].map((item) => (
        <div className="border-t border-[var(--line)] py-8" key={item}>
          <div className="grid gap-5 sm:grid-cols-[5rem_1fr_auto]">
            <Skeleton className="h-12 w-14" />
            <div className="space-y-3">
              <Skeleton className="h-3 w-24" />
              <Skeleton className="h-8 w-40" />
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
