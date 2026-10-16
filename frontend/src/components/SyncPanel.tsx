import type { Account } from '../api/client'
import { useDisconnect, useStartSync, useSyncStatus } from '../api/hooks'
import { formatNumber, formatRelative } from '../lib/format'

export function SyncPanel({ account }: { account: Account }) {
  const { data: status } = useSyncStatus()
  const startSync = useStartSync()
  const disconnect = useDisconnect()
  const running = status?.state === 'running'

  const onDisconnect = () => {
    const ok = window.confirm(
      'Disconnect this account? Access will be revoked and the local cache deleted. ' +
        'Your mailbox itself is not affected.',
    )
    if (ok) disconnect.mutate()
  }

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <p className="text-sm text-slate-500">Connected as</p>
          <p className="font-medium text-slate-900">{account.email}</p>
          <p className="mt-1 text-xs text-slate-500">
            {account.last_synced_at
              ? `${formatNumber(account.message_count)} messages cached · synced ${formatRelative(account.last_synced_at)}`
              : 'Not synced yet'}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={onDisconnect}
            disabled={running || disconnect.isPending}
            className="text-sm text-slate-500 hover:text-slate-700 disabled:opacity-50"
          >
            Disconnect
          </button>
          <button
            type="button"
            onClick={() => startSync.mutate({})}
            disabled={running || startSync.isPending}
            className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-indigo-500 disabled:opacity-50"
          >
            {running ? 'Syncing…' : 'Sync now'}
          </button>
        </div>
      </div>

      {running && status && <SyncProgress processed={status.processed} total={status.total} />}
      {status?.state === 'error' && (
        <p role="alert" className="mt-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
          Sync failed: {status.error}
        </p>
      )}
      {startSync.isError && (
        <p role="alert" className="mt-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
          {startSync.error.message}
        </p>
      )}
    </div>
  )
}

function SyncProgress({ processed, total }: { processed: number; total: number }) {
  const pct = total > 0 ? Math.round((processed / total) * 100) : 0
  return (
    <div className="mt-5">
      <div className="mb-1 flex justify-between text-xs text-slate-500">
        <span>{total > 0 ? 'Fetching message details' : 'Listing messages'}</span>
        {total > 0 && (
          <span>
            {formatNumber(processed)} / {formatNumber(total)}
          </span>
        )}
      </div>
      <div
        className="h-2 overflow-hidden rounded-full bg-slate-100"
        role="progressbar"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div className="h-full bg-indigo-500 transition-all" style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}
