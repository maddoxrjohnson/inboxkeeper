import { useEffect, useState } from 'react'

export interface Notice {
  kind: 'success' | 'error'
  text: string
}

// The OAuth callback lands back here with ?connected=1 or ?auth_error=...
function readNotice(): Notice | null {
  const params = new URLSearchParams(window.location.search)
  const error = params.get('auth_error')
  if (error) return { kind: 'error', text: error }
  if (params.has('connected')) return { kind: 'success', text: 'Gmail connected.' }
  return null
}

export function useAuthRedirectNotice() {
  const [notice, setNotice] = useState<Notice | null>(readNotice)

  useEffect(() => {
    if (notice) window.history.replaceState(null, '', window.location.pathname)
  }, [notice])

  return { notice, dismiss: () => setNotice(null) }
}
