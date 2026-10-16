import type { Notice } from '../hooks/useAuthRedirectNotice'

export function AuthBanner({ notice, onDismiss }: { notice: Notice; onDismiss: () => void }) {
  const styles =
    notice.kind === 'success'
      ? 'border-emerald-200 bg-emerald-50 text-emerald-800'
      : 'border-red-200 bg-red-50 text-red-800'
  return (
    <div
      role={notice.kind === 'error' ? 'alert' : 'status'}
      className={`flex items-start justify-between gap-4 rounded-lg border px-4 py-3 text-sm ${styles}`}
    >
      <span>{notice.text}</span>
      <button
        type="button"
        onClick={onDismiss}
        aria-label="Dismiss"
        className="opacity-60 hover:opacity-100"
      >
        ×
      </button>
    </div>
  )
}
