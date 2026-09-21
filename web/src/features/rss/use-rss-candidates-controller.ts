import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"

import type { RssCandidateView } from "./types"
import { confirmRssCandidate, fetchRssCandidatesPage, ignoreRssCandidate } from "./rss-api"

const QUERY_KEY = ["rss-candidates"] as const

export function useRssCandidatesController(status: RssCandidateView) {
  const queryClient = useQueryClient()
  const candidates = useInfiniteQuery({
    queryKey: [...QUERY_KEY, status],
    queryFn: ({ pageParam }) => fetchRssCandidatesPage(pageParam, status),
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
    onSuccess: async () => {
      toast.success("已保存到素材库")
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
    ignore: ignore.mutate,
    confirm: confirm.mutate,
    busyId: ignore.isPending ? ignore.variables : confirm.isPending ? confirm.variables : null,
  }
}
