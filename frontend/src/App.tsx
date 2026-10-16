import { useEffect, useRef } from 'react'
import { useAccount, useHealth, useStartSync } from './api/hooks'
import { AuthBanner } from './components/AuthBanner'
import { ConnectCard } from './components/ConnectCard'
import { SetupGuide } from './components/SetupGuide'
import { StatsOverview } from './components/StatsOverview'
import { SyncPanel } from './components/SyncPanel'
import { useAuthRedirectNotice } from './hooks/useAuthRedirectNotice'

function BackendStatus() {
  const { data, isPending, isError } = useHealth()

  if (isPending) return <span className="text-sm text-slate-500">Connecting…</span>
  if (isError) return <span className="text-sm text-red-600">Backend unreachable</span>
  return <span className="text-sm text-emerald-600">Connected (v{data.version})</span>
}

function Main() {
  const { data: account, isPending, isError } = useAccount()
  const { notice, dismiss } = useAuthRedirectNotice()
  const startSync = useStartSync()

  // Kick off the first sync right after the user connects.
  const autoSynced = useRef(false)
  useEffect(() => {
    if (autoSynced.current || notice?.kind !== 'success') return
    if (account?.connected && !account.last_synced_at) {
      autoSynced.current = true
      startSync.mutate({})
    }
  }, [account, notice, startSync])

  if (isPending) return <p className="text-sm text-slate-500">Loading…</p>
  if (isError) {
    return (
      <p className="text-sm text-slate-600">
        Start the backend with <code>uv run inboxkeeper</code> to continue.
      </p>
    )
  }

  return (
    <div className="space-y-6">
      {notice && <AuthBanner notice={notice} onDismiss={dismiss} />}
      {!account.has_client_secrets && !account.connected ? (
        <SetupGuide secretsPath={account.client_secrets_path} />
      ) : !account.connected ? (
        <ConnectCard />
      ) : (
        <>
          <SyncPanel account={account} />
          {account.message_count > 0 && <StatsOverview />}
        </>
      )}
    </div>
  )
}

export default function App() {
  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-4">
          <h1 className="text-lg font-semibold">inboxkeeper</h1>
          <BackendStatus />
        </div>
      </header>
      <main className="mx-auto max-w-5xl px-6 py-10">
        <Main />
      </main>
    </div>
  )
}
