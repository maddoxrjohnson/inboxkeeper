export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const resp = await fetch(`/api${path}`, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!resp.ok) {
    let detail = `${method} ${path} failed with ${resp.status}`
    try {
      const data = (await resp.json()) as { detail?: unknown }
      if (typeof data.detail === 'string') detail = data.detail
    } catch {
      // Non-JSON error body; keep the generic message.
    }
    throw new ApiError(resp.status, detail)
  }
  if (resp.status === 204) return undefined as T
  return (await resp.json()) as T
}

export const apiGet = <T>(path: string) => request<T>('GET', path)
export const apiPost = <T>(path: string, body?: unknown) => request<T>('POST', path, body)

export interface Health {
  status: string
  version: string
}

export interface Account {
  connected: boolean
  email: string | null
  has_client_secrets: boolean
  client_secrets_path: string
  last_synced_at: string | null
  message_count: number
}

export interface SyncStatus {
  state: 'idle' | 'running' | 'done' | 'error'
  processed: number
  total: number
  mode: string | null
  fetched: number | null
  removed: number | null
  error: string | null
  started_at: string | null
  finished_at: string | null
}

export interface SenderStat {
  email: string
  name: string
  count: number
  total_size: number
}

export interface Stats {
  total: number
  inbox: number
  inbox_unread: number
  spam: number
  total_size: number
  top_senders: SenderStat[]
}

export type ActionKind = 'archive' | 'trash' | 'mark_read' | 'not_spam'

export interface ActionBatch {
  id: number
  kind: ActionKind
  status: 'pending' | 'applied' | 'failed' | 'undone'
  created_at: string
  undone_at: string | null
  applied_count: number
  skipped_count: number
  total_size: number
  error: string | null
  can_undo: boolean
}

export const getHealth = () => apiGet<Health>('/health')
export const getAccount = () => apiGet<Account>('/account')
export const getSyncStatus = () => apiGet<SyncStatus>('/sync')
export const startSync = (opts: { full?: boolean } = {}) => apiPost<SyncStatus>('/sync', opts)
export const disconnect = () => apiPost<void>('/auth/disconnect')
export const getStats = () => apiGet<Stats>('/stats')
export const getActions = () => apiGet<ActionBatch[]>('/actions')
export const undoAction = (id: number) => apiPost<ActionBatch>(`/actions/${id}/undo`)

// Plain navigation, not fetch: the backend redirects the browser to Google.
export const GOOGLE_SIGN_IN_URL = '/api/auth/google/start'
