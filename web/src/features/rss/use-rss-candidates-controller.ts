import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"

import { ApiError } from "@/lib/api"
import type { RssCandidateView } from "./types"
import { confirmRssCandidate, fetchRssCandidatesPage, ignoreRssCandidate } from "./rss-api"

const QUERY_KEY = ["rss-candidates"] as const

/** 409 = 飞书侧状态已变更（先读后写冲突）：提示并刷新列表，不做强制覆盖。 */
function isConflict(error: Error): boolean {
  return error instanceof ApiError && error.status === 409
}

export function useRssCandidatesController(status: RssCandidateView) {
  const queryClient = useQueryClient()
  const candidates = useInfiniteQuery({
    queryKey: [...QUERY_KEY, status],
    queryFn: ({ pageParam }) => fetchRssCandidatesPage(pageParam, status),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  })
  const onReviewError = async (error: Error) => {
    if (isConflict(error)) {
      toast.error("该条已在飞书侧变更，已刷新")
      await queryClient.invalidateQueries({ queryKey: QUERY_KEY })
      return
    }
    toast.error(error.message)
  }
  const ignore = useMutation({
    mutationFn: ignoreRssCandidate,
    onSuccess: async () => {
      toast.success("已忽略候选")
      await queryClient.invalidateQueries({ queryKey: QUERY_KEY })
    },
    onError: onReviewError,
  })
  const confirm = useMutation({
    mutationFn: confirmRssCandidate,
    onSuccess: async () => {
      toast.success("已保存到素材库")
      await queryClient.invalidateQueries({ queryKey: QUERY_KEY })
    },
    onError: onReviewError,
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
