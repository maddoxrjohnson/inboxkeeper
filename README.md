# inboxkeeper

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

## License

MIT
