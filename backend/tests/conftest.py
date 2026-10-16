from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from inboxkeeper.api.app import create_app
from inboxkeeper.api.context import AppContext
from inboxkeeper.config import Settings
from inboxkeeper.providers.fake import FakeProvider


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path, allowed_hosts=["127.0.0.1", "localhost", "testserver"])


@pytest.fixture
def provider() -> FakeProvider:
    return FakeProvider(email="me@example.com")


@pytest.fixture
def app(settings: Settings, provider: FakeProvider) -> FastAPI:
    return create_app(settings, provider_factory=lambda: provider)


@pytest.fixture
def ctx(app: FastAPI) -> AppContext:
    context: AppContext = app.state.ctx
    return context


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app, follow_redirects=False)


@pytest.fixture
def connected(ctx: AppContext) -> None:
    """Pretend the user has finished the OAuth flow."""
    ctx.auth.token_path.write_text("{}")
