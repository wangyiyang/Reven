import { useMutation, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"

import { createTalent, deleteTalent, talentsKeys, updateTalent } from "./talents-api"
import type { TalentInput } from "./types"

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "请求失败"
}

export function useCreateTalent(onSaved: () => void) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: createTalent,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: talentsKeys.talents })
      onSaved()
      toast.success("人才已添加")
    },
    onError: (error) => toast.error(errorMessage(error)),
  })
}

export function useUpdateTalent(onSaved: () => void) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ talentId, input }: { talentId: string; input: TalentInput }) =>
      updateTalent(talentId, input),
    onSuccess: async (talent) => {
      queryClient.setQueryData(talentsKeys.talent(talent.id), talent)
      await queryClient.invalidateQueries({ queryKey: talentsKeys.talents })
      onSaved()
      toast.success("人才已更新")
    },
    onError: (error) => toast.error(errorMessage(error)),
  })
}

export function useDeleteTalent(onDeleted: () => void) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: deleteTalent,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: talentsKeys.talents })
      onDeleted()
      toast.success("人才已删除")
    },
    onError: (error) => toast.error(errorMessage(error)),
  })
}
