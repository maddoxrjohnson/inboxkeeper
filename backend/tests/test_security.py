from fastapi.testclient import TestClient

from inboxkeeper.api.app import create_app
from inboxkeeper.config import Settings


def make_client(settings: Settings) -> TestClient:
    app = create_app(settings)

    @app.post("/api/_echo")
    def echo() -> dict[str, bool]:
        return {"ok": True}

    return TestClient(app)


def test_rejects_unknown_host_header(settings: Settings) -> None:
    client = make_client(settings)
    resp = client.get("/api/health", headers={"host": "evil.example.com"})
    assert resp.status_code == 400


def test_rejects_cross_origin_post(settings: Settings) -> None:
    client = make_client(settings)
    resp = client.post("/api/_echo", headers={"origin": "https://evil.example.com"})
    assert resp.status_code == 403


def test_allows_post_from_frontend(settings: Settings) -> None:
    client = make_client(settings)
    resp = client.post("/api/_echo", headers={"origin": "http://localhost:5173"})
    assert resp.status_code == 200


def test_allows_post_without_origin(settings: Settings) -> None:
    assert make_client(settings).post("/api/_echo").status_code == 200


def test_get_requests_are_not_origin_checked(settings: Settings) -> None:
    client = make_client(settings)
    resp = client.get("/api/health", headers={"origin": "https://evil.example.com"})
    assert resp.status_code == 200
