import { Card } from './Card'

const REPO_DOCS = 'https://github.com/maddoxrjohnson/inboxkeeper/blob/main/docs/setup-gmail.md'

export function SetupGuide({ secretsPath }: { secretsPath: string }) {
  return (
    <Card title="Set up Gmail access">
      <p className="mb-4 text-sm text-slate-600">
        inboxkeeper talks to Gmail with your own Google Cloud credentials, so your mail never
        passes through anyone else&apos;s servers. This is a one-time, five-minute setup.
      </p>
      <ol className="mb-4 list-decimal space-y-2 pl-5 text-sm text-slate-700">
        <li>Create a Google Cloud project and enable the Gmail API.</li>
        <li>Configure the OAuth consent screen and add yourself as a test user.</li>
        <li>
          Create an OAuth client ID of type <strong>Desktop app</strong> and download its JSON.
        </li>
        <li>
          Save the file as{' '}
          <code className="rounded bg-slate-100 px-1.5 py-0.5 text-xs">{secretsPath}</code>
        </li>
      </ol>
      <div className="flex items-center gap-4">
        <a
          href={REPO_DOCS}
          target="_blank"
          rel="noreferrer"
          className="text-sm font-medium text-indigo-600 hover:text-indigo-500"
        >
          Step-by-step guide →
        </a>
        <button
          type="button"
          onClick={() => window.location.reload()}
          className="text-sm text-slate-500 hover:text-slate-700"
        >
          I&apos;ve saved it, check again
        </button>
      </div>
    </Card>
  )
}
