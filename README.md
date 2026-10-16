# inboxkeeper

[![CI](https://github.com/maddoxrjohnson/inboxkeeper/actions/workflows/ci.yml/badge.svg)](https://github.com/maddoxrjohnson/inboxkeeper/actions/workflows/ci.yml)

A local, privacy-first tool for cleaning up a cluttered inbox: unsubscribe from
mailing lists you never read, rescue real mail from the spam folder, and clear
out old mail that's eating your storage.

It's built to be conservative. Nothing in your mailbox changes until you review
and approve it, every action can be undone, and the tool never permanently
deletes anything.

> Work in progress. Gmail is supported first; IMAP and Outlook are planned.

## Safety guarantees

- **Review before anything changes.** Scans only produce suggestions. Nothing
  in your mailbox is touched until you approve it.
- **No permanent deletion.** The app only requests Gmail's `gmail.modify`
  scope, which can't permanently delete mail. The furthest it goes is the
  trash, which Gmail keeps for 30 days.
- **Local only.** Message headers are cached in a SQLite file on your machine.
  Message bodies are never downloaded, and nothing is sent anywhere except to
  Gmail itself.
- **Hardened local API.** The backend only accepts requests addressed to
  localhost and rejects state-changing requests from other origins, so a web
  page you visit can't drive it.

## Stack

- **Backend:** Python, FastAPI, SQLite
- **Frontend:** React, TypeScript, Vite
- **Classification:** rule-based scoring plus a small scikit-learn model trained
  locally on your own decisions

## Getting started

1. Follow [docs/setup-gmail.md](docs/setup-gmail.md) to create a Google OAuth
   client and save it as `~/.inboxkeeper/credentials.json`.
2. Start the backend and frontend as shown below, open
   http://localhost:5173 and click **Connect Gmail**.

## How it works

```
React UI  ──/api──▶  FastAPI  ──▶  MailProvider ──▶ Gmail API
                        │              (Gmail now; IMAP/Outlook later)
                        ▼
                     SQLite (headers only)
```

- **Providers** implement a small `MailProvider` protocol (list ids, fetch
  metadata, incremental changes, label/trash). Scanners and the UI only work
  against that interface and the local cache.
- **Sync** does a resumable full sync on first run, then incremental syncs
  using Gmail's history API. Metadata is fetched through the batch endpoint
  with exponential backoff on rate limits.
- **Tests** run against an in-memory `FakeProvider` and a fake Gmail HTTP
  layer, so the real client library is exercised without network access.

## Development

Requires Python 3.12+ with [uv](https://docs.astral.sh/uv/), and Node 22+.

```bash
# backend (http://127.0.0.1:8765)
cd backend
uv sync
uv run inboxkeeper

# frontend (http://localhost:5173), in a second terminal
cd frontend
npm install
npm run dev
```

Checks:

```bash
cd backend && uv run ruff check . && uv run mypy && uv run pytest
cd frontend && npm run lint && npm test && npm run build
```

## License

MIT
