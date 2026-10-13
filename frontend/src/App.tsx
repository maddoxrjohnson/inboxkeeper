import { useQuery } from '@tanstack/react-query'
import { getHealth } from './api/client'

function BackendStatus() {
  const { data, isPending, isError } = useQuery({ queryKey: ['health'], queryFn: getHealth })

  if (isPending) return <span className="text-slate-500">Connecting…</span>
  if (isError) return <span className="text-red-600">Backend unreachable</span>
  return <span className="text-emerald-600">Connected (v{data.version})</span>
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
        <p className="text-slate-600">Connect an account to get started.</p>
      </main>
    </div>
  )
}
