# inboxkeeper

[![CI](https://github.com/maddoxrjohnson/inboxkeeper/actions/workflows/ci.yml/badge.svg)](https://github.com/maddoxrjohnson/inboxkeeper/actions/workflows/ci.yml)

A local, privacy-first tool for cleaning up a cluttered inbox: unsubscribe from
mailing lists you never read, rescue real mail from the spam folder, and clear
out old mail that's eating your storage.

It's built to be conservative. Nothing in your mailbox changes until you review
and approve it, every action can be undone, and the tool never permanently
deletes anything.

> Work in progress. Gmail is supported first; IMAP and Outlook are planned.

## Stack

- **Backend:** Python, FastAPI, SQLite
- **Frontend:** React, TypeScript, Vite
- **Classification:** rule-based scoring plus a small scikit-learn model trained
  locally on your own decisions

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
