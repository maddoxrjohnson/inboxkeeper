import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Account, Stats, SyncStatus } from './api/client'
import App from './App'
import { mockApi } from './test/mockApi'

const health = { status: 'ok', version: '0.1.0' }
const idle: SyncStatus = {
  state: 'idle',
  processed: 0,
  total: 0,
  mode: null,
  fetched: null,
  removed: null,
  error: null,
  started_at: null,
  finished_at: null,
}
const baseAccount: Account = {
  connected: false,
  email: null,
  has_client_secrets: false,
  client_secrets_path: '/home/me/.inboxkeeper/credentials.json',
  last_synced_at: null,
  message_count: 0,
}
const stats: Stats = {
  total: 1200,
  inbox: 300,
  inbox_unread: 42,
  spam: 7,
  total_size: 50 * 1024 ** 2,
  top_senders: [{ email: 'deals@shop.com', name: 'Shop', count: 180, total_size: 9 * 1024 ** 2 }],
}

function renderApp() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  )
}

function withAccount(account: Partial<Account>, extra: Record<string, object> = {}) {
  return mockApi({
    'GET /api/health': health,
    'GET /api/account': { ...baseAccount, ...account },
    'GET /api/sync': idle,
    ...extra,
  })
}

describe('App', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    window.history.replaceState(null, '', '/')
  })

  it('reports when the backend is down', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 502 })))
    renderApp()

    expect(await screen.findByText('Backend unreachable')).toBeInTheDocument()
  })

  it('walks through setup when no OAuth client is configured', async () => {
    withAccount({})
    renderApp()

    expect(await screen.findByText('Set up Gmail access')).toBeInTheDocument()
    expect(screen.getByText(baseAccount.client_secrets_path)).toBeInTheDocument()
    expect(await screen.findByText('Connected (v0.1.0)')).toBeInTheDocument()
  })

  it('offers to connect once the OAuth client exists', async () => {
    withAccount({ has_client_secrets: true })
    renderApp()

    const link = await screen.findByRole('link', { name: 'Connect Gmail' })
    expect(link).toHaveAttribute('href', '/api/auth/google/start')
  })

  it('shows the account and overview when connected', async () => {
    withAccount(
      {
        has_client_secrets: true,
        connected: true,
        email: 'me@gmail.com',
        last_synced_at: new Date().toISOString(),
        message_count: 1200,
      },
      { 'GET /api/stats': stats },
    )
    renderApp()

    expect(await screen.findByText('me@gmail.com')).toBeInTheDocument()
    expect(await screen.findByText('Shop')).toBeInTheDocument()
    expect(screen.getByText('50.0 MB')).toBeInTheDocument()
    expect(screen.getByText('42')).toBeInTheDocument()
  })

  it('shows sign-in errors from the OAuth redirect', async () => {
    window.history.replaceState(null, '', '/?auth_error=Sign-in%20was%20cancelled.')
    withAccount({ has_client_secrets: true })
    renderApp()

    expect(await screen.findByRole('alert')).toHaveTextContent('Sign-in was cancelled.')
    expect(window.location.search).toBe('')
  })

  it('starts the first sync right after connecting', async () => {
    window.history.replaceState(null, '', '/?connected=1')
    const running: SyncStatus = { ...idle, state: 'running', processed: 10, total: 100 }
    const fetchMock = withAccount(
      { has_client_secrets: true, connected: true, email: 'me@gmail.com' },
      { 'POST /api/sync': running },
    )
    renderApp()

    expect(await screen.findByRole('progressbar')).toHaveAttribute('aria-valuenow', '10')
    const posts = fetchMock.mock.calls.filter(([, init]) => init?.method === 'POST')
    expect(posts).toHaveLength(1)
  })
})
