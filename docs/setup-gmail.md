# Connecting Gmail

inboxkeeper uses your own Google Cloud OAuth client instead of a shared one.
Your mail goes straight from Google to your machine, and there's no
third-party app sitting in the middle with access to your inbox.

Setup takes about five minutes and only has to be done once.

## 1. Create a project and enable the Gmail API

1. Go to the [Google Cloud console](https://console.cloud.google.com/) and
   create a new project (any name, e.g. `inboxkeeper`).
2. Open **APIs & Services → Library**, search for **Gmail API** and click
   **Enable**.

## 2. Configure the consent screen

1. Open **Google Auth Platform** (formerly *OAuth consent screen*) and click
   **Get started**.
2. Enter an app name and your email address. For **Audience** choose
   **External**.
3. Under **Audience → Test users**, add the Gmail address you want to clean up.

You can leave the app in **Testing** mode. Google will show an "unverified
app" warning when you sign in; that's expected for a personal client.

## 3. Create the OAuth client

1. Open **Google Auth Platform → Clients** and click **Create client**.
2. Choose **Desktop app** as the application type. (A *Web application*
   client won't work.)
3. Click **Create**, then **Download JSON**.

## 4. Hand the file to inboxkeeper

Save the downloaded file as:

```
~/.inboxkeeper/credentials.json
```

On Windows with WSL, `~` means your Linux home, not `C:\Users\<you>`. If the
file landed in your Windows Downloads folder, copy it across from a WSL shell:

```bash
mkdir -p ~/.inboxkeeper
cp /mnt/c/Users/<you>/Downloads/client_secret_*.json ~/.inboxkeeper/credentials.json
```

Then open the app, click **Connect Gmail** and approve access. Make sure the
Gmail permission checkbox stays ticked on Google's consent screen.

## What access is requested

inboxkeeper asks for a single scope, `gmail.modify`. It allows reading
message metadata, changing labels (archive, mark as spam/not spam) and moving
messages to the trash. It does **not** allow permanent deletion, so anything
inboxkeeper trashes can be recovered from Gmail's trash for 30 days.

Only message headers (sender, subject, date, labels, size) are stored
locally, in `~/.inboxkeeper/inboxkeeper.db`. Message bodies are never
downloaded. The access token lives in `~/.inboxkeeper/token.json` with
owner-only permissions. **Disconnect** in the app revokes the token with
Google, deletes it and clears the local cache.

## Troubleshooting

**"Access blocked: app has not completed the Google verification process"**:
the account you're signing in with isn't listed under *Test users*.

**Asked to reconnect every week**: Google expires refresh tokens after 7 days
for apps in Testing mode. Publishing the app (Audience → Publish app) removes
the limit; for a personal client you can do this without going through
verification.

**"The OAuth client must be of type Desktop app"**: the JSON came from a Web
application client. Create a new Desktop app client and download that instead.

**First sync is slow**: Gmail limits how many requests each user can make per
minute, and the limit on a new Google Cloud project can be far below the
documented one. inboxkeeper adapts its pace to whatever your project allows,
which in testing has been around 5 messages a second. The first sync only
happens once (later syncs fetch just what changed) and it resumes if
interrupted. You can see your project's limit under **APIs & Services →
Gmail API → Quotas & System Limits**.

**Data directory elsewhere**: set `INBOXKEEPER_DATA_DIR` before starting the
backend to keep everything in a different folder.
