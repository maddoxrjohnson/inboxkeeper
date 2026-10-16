import { useStats } from '../api/hooks'
import { formatBytes, formatNumber } from '../lib/format'
import { Card } from './Card'

export function StatsOverview() {
  const { data: stats, isPending, isError } = useStats(true)

  if (isPending) return <p className="text-sm text-slate-500">Loading overview…</p>
  if (isError) return <p className="text-sm text-red-600">Couldn&apos;t load the overview.</p>
  if (stats.total === 0) return null

  const tiles = [
    { label: 'Messages', value: formatNumber(stats.total) },
    { label: 'In inbox', value: formatNumber(stats.inbox) },
    { label: 'Unread in inbox', value: formatNumber(stats.inbox_unread) },
    { label: 'Storage used', value: formatBytes(stats.total_size) },
  ]

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        {tiles.map((t) => (
          <div key={t.label} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <p className="text-xs text-slate-500">{t.label}</p>
            <p className="mt-1 text-2xl font-semibold text-slate-900">{t.value}</p>
          </div>
        ))}
      </div>

      <Card title="Top senders">
        <table className="w-full text-left text-sm">
          <thead className="text-xs text-slate-500">
            <tr>
              <th className="pb-2 font-medium">Sender</th>
              <th className="pb-2 text-right font-medium">Messages</th>
              <th className="pb-2 text-right font-medium">Size</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {stats.top_senders.map((s) => (
              <tr key={s.email}>
                <td className="py-2">
                  <p className="font-medium text-slate-900">{s.name || s.email}</p>
                  {s.name && <p className="text-xs text-slate-500">{s.email}</p>}
                </td>
                <td className="py-2 text-right tabular-nums">{formatNumber(s.count)}</td>
                <td className="py-2 text-right tabular-nums text-slate-500">
                  {formatBytes(s.total_size)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  )
}
