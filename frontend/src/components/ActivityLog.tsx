import { useState } from 'react'
import type { ActionBatch, ActionKind } from '../api/client'
import { useActions, useUndoAction } from '../api/hooks'
import { formatBytes, formatNumber, formatRelative } from '../lib/format'
import { Card } from './Card'

const VERBS: Record<ActionKind, string> = {
  archive: 'Archived',
  trash: 'Moved to trash',
  mark_read: 'Marked as read',
  not_spam: 'Moved out of spam',
}

function describe(batch: ActionBatch): string {
  const n = batch.applied_count
  const parts = [`${VERBS[batch.kind]} ${formatNumber(n)} ${n === 1 ? 'email' : 'emails'}`]
  if (batch.total_size > 0) parts.push(formatBytes(batch.total_size))
  if (batch.skipped_count > 0) parts.push(`${formatNumber(batch.skipped_count)} skipped`)
  return parts.join(' · ')
}

function StatusNote({ batch }: { batch: ActionBatch }) {
  if (batch.status === 'undone') return <span className="text-xs text-slate-500">Undone</span>
  if (batch.status === 'failed') {
    return <span className="text-xs text-red-600">Failed partway: {batch.error}</span>
  }
  return null
}

function ActivityRow({ batch }: { batch: ActionBatch }) {
  const undo = useUndoAction()
  const [confirming, setConfirming] = useState(false)

  return (
    <li className="py-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-sm font-medium text-slate-900">{describe(batch)}</p>
          <p className="text-xs text-slate-500">
            {formatRelative(batch.created_at)} <StatusNote batch={batch} />
          </p>
        </div>
        {batch.can_undo &&
          (confirming ? (
            <div className="flex items-center gap-2 text-sm">
              <span className="text-slate-600">Undo this?</span>
              <button
                type="button"
                onClick={() => {
                  setConfirming(false)
                  undo.mutate(batch.id)
                }}
                className="rounded-lg bg-indigo-600 px-3 py-1 font-medium text-white hover:bg-indigo-500"
              >
                Yes, undo
              </button>
              <button
                type="button"
                onClick={() => setConfirming(false)}
                className="text-slate-500 hover:text-slate-700"
              >
                Cancel
              </button>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => setConfirming(true)}
              disabled={undo.isPending}
              className="rounded-lg border border-slate-300 px-3 py-1 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50"
            >
              {undo.isPending ? 'Undoing…' : 'Undo'}
            </button>
          ))}
      </div>
      {undo.isError && (
        <p role="alert" className="mt-2 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
          {undo.error.message}
        </p>
      )}
    </li>
  )
}

export function ActivityLog() {
  const { data: actions } = useActions()
  if (!actions || actions.length === 0) return null

  return (
    <Card title="Recent activity">
      <ul className="divide-y divide-slate-100">
        {actions.map((batch) => (
          <ActivityRow key={batch.id} batch={batch} />
        ))}
      </ul>
    </Card>
  )
}
