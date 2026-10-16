import { GOOGLE_SIGN_IN_URL } from '../api/client'
import { Card } from './Card'

export function ConnectCard() {
  return (
    <Card title="Connect your Gmail account">
      <p className="mb-2 text-sm text-slate-600">
        inboxkeeper asks for permission to read and organise your mail. It can move messages to
        the trash, where Gmail keeps them for 30 days, but it can never permanently delete
        anything.
      </p>
      <p className="mb-5 text-sm text-slate-600">
        Nothing in your mailbox changes until you review and approve it.
      </p>
      <a
        href={GOOGLE_SIGN_IN_URL}
        className="inline-flex items-center rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-indigo-500"
      >
        Connect Gmail
      </a>
    </Card>
  )
}
