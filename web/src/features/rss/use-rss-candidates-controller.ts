import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"

import { safeNotionUrl } from "@/lib/external-url"
import { confirmRssCandidate, fetchRssCandidatesPage, ignoreRssCandidate } from "./rss-api"

const QUERY_KEY = ["rss-candidates"] as const

export function useRssCandidatesController() {
  const queryClient = useQueryClient()
  const candidates = useInfiniteQuery({
    queryKey: QUERY_KEY,
    queryFn: ({ pageParam }) => fetchRssCandidatesPage(pageParam),
    initialPageParam: 1,
    getNextPageParam: (last) => (last.page * last.page_size < last.total ? last.page + 1 : undefined),
  })
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
  const items = candidates.data?.pages.flatMap((page) => page.items) ?? []
  return {
    candidates,
    items,
    total: candidates.data?.pages[0]?.total,
    hasNextPage: candidates.hasNextPage,
    isFetchingNextPage: candidates.isFetchingNextPage,
    fetchNextPage: candidates.fetchNextPage,
    ignore: ignore.mutateAsync,
    confirm: confirm.mutateAsync,
    busyId: ignore.isPending ? ignore.variables : confirm.isPending ? confirm.variables : null,
  }
}
