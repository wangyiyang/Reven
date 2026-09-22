import { Button } from "@/components/ui/button"

export function ErrorPanel({ title, message, retry }: { title: string; message: string; retry: () => void }) {
  return (
    <div className="border border-[var(--danger)] bg-[var(--faint)] p-5 text-sm text-[var(--danger)]" role="alert">
      <p>{title}：{message}</p>
      <Button className="mt-4" onClick={retry} size="sm" variant="outline">重新读取</Button>
    </div>
  )
}
