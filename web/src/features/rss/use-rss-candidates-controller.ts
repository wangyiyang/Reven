import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"

import { safeNotionUrl } from "@/lib/external-url"
import { confirmRssCandidate, fetchRssCandidates, ignoreRssCandidate } from "./rss-api"

const QUERY_KEY = ["rss-candidates"] as const

export function useRssCandidatesController() {
  const queryClient = useQueryClient()
  const candidates = useQuery({ queryKey: QUERY_KEY, queryFn: fetchRssCandidates })
  const ignore = useMutation({
    mutationFn: ignoreRssCandidate,
    onSuccess: async () => {
      toast.success("已忽略候选")
      await queryClient.invalidateQueries({ queryKey: QUERY_KEY })
    },
    onError: (error: Error) => toast.error(error.message),
  })
  const confirm = useMutation({
    mutationFn: confirmRssCandidate,
    onSuccess: async (result) => {
      const notionUrl = safeNotionUrl(result.notion_url)
      toast.success("已推送到 Notion Inbox", notionUrl ? {
        action: { label: "打开页面", onClick: () => window.open(notionUrl, "_blank", "noopener,noreferrer") },
      } : undefined)
      await queryClient.invalidateQueries({ queryKey: QUERY_KEY })
    },
    onError: (error: Error) => toast.error(error.message),
  })
  return {
    candidates,
    ignore: ignore.mutateAsync,
    confirm: confirm.mutateAsync,
    busyId: ignore.isPending ? ignore.variables : confirm.isPending ? confirm.variables : null,
  }
}
