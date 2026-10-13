from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from inboxkeeper.api.app import create_app
from inboxkeeper.config import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path)


@pytest.fixture
def client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings))
