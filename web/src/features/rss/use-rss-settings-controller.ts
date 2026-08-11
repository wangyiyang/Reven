import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useCallback, useRef, useState } from "react"
import { toast } from "sonner"

import {
  fetchRssKeywords,
  fetchRssSources,
  runRssSettingsAction,
  type RssSettingsAction,
} from "./rss-api"

export function useRssSettingsController() {
  const queryClient = useQueryClient()
  const actionLocked = useRef(false)
  const [isActionLocked, setIsActionLocked] = useState(false)
  const sources = useQuery({ queryKey: ["rss-sources"], queryFn: fetchRssSources })
  const keywords = useQuery({ queryKey: ["rss-keywords"], queryFn: fetchRssKeywords })
  const mutation = useMutation({
    mutationFn: runRssSettingsAction,
    onSuccess: async (result) => {
      await queryClient.invalidateQueries({ queryKey: [result.queryKey] })
      toast.success(result.message)
    },
    onError: (error: Error) => toast.error(error.message),
  })
  const execute = useCallback(async (action: RssSettingsAction): Promise<boolean> => {
    if (actionLocked.current) return false
    actionLocked.current = true
    setIsActionLocked(true)
    try {
      await mutation.mutateAsync(action)
      return true
    } catch {
      return false
    } finally {
      actionLocked.current = false
      setIsActionLocked(false)
    }
  }, [mutation])
  return { sources, keywords, execute, isActionLocked }
}
