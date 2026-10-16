import threading
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import Engine

from inboxkeeper.auth.google import GoogleAuth
from inboxkeeper.config import Settings
from inboxkeeper.providers.base import MailProvider
from inboxkeeper.providers.gmail import GmailProvider
from inboxkeeper.sync import BackgroundSync

ProviderFactory = Callable[[], MailProvider]


class NotConnectedError(Exception):
    pass


def gmail_provider_factory(auth: GoogleAuth) -> ProviderFactory:
    def make() -> MailProvider:
        creds = auth.load_credentials()
        if creds is None:
            raise NotConnectedError("Gmail isn't connected, or access has expired.")
        return GmailProvider.from_credentials(creds)

    return make


class AppContext:
    def __init__(
        self,
        settings: Settings,
        engine: Engine,
        auth: GoogleAuth,
        provider_factory: ProviderFactory,
    ) -> None:
        self.settings = settings
        self.engine = engine
        self.auth = auth
        self.provider_factory = provider_factory
        self.sync = BackgroundSync(engine, provider_factory)
        # Held while an action or undo is changing the mailbox.
        self.action_lock = threading.Lock()
        self._account_email: str | None = None

    @property
    def connected(self) -> bool:
        return self.auth.has_token()

    def account_email(self) -> str | None:
        if not self.connected:
            return None
        if self._account_email is None:
            self._account_email = self.provider_factory().get_account_email()
        return self._account_email

    def forget_account(self) -> None:
        self._account_email = None


def get_context(request: Request) -> AppContext:
    ctx: AppContext = request.app.state.ctx
    return ctx


Ctx = Annotated[AppContext, Depends(get_context)]
