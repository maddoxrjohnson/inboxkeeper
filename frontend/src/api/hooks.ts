import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'
import { disconnect, getAccount, getHealth, getStats, getSyncStatus, startSync } from './client'

export const useHealth = () => useQuery({ queryKey: ['health'], queryFn: getHealth })

export const useAccount = () => useQuery({ queryKey: ['account'], queryFn: getAccount })

export const useStats = (enabled: boolean) =>
  useQuery({ queryKey: ['stats'], queryFn: getStats, enabled })

export function useSyncStatus() {
  const queryClient = useQueryClient()
  const query = useQuery({
    queryKey: ['sync'],
    queryFn: getSyncStatus,
    refetchInterval: (q) => (q.state.data?.state === 'running' ? 1000 : false),
  })

  // When a running sync finishes, everything derived from the cache is stale.
  const previous = useRef(query.data?.state)
  useEffect(() => {
    const state = query.data?.state
    if (previous.current === 'running' && state !== 'running') {
      void queryClient.invalidateQueries({ queryKey: ['account'] })
      void queryClient.invalidateQueries({ queryKey: ['stats'] })
    }
    previous.current = state
  }, [query.data?.state, queryClient])

  return query
}

export function useStartSync() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: startSync,
    onSuccess: (status) => queryClient.setQueryData(['sync'], status),
  })
}

export function useDisconnect() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: disconnect,
    onSuccess: () => queryClient.invalidateQueries(),
  })
}
