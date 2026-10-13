from fastapi.testclient import TestClient

from inboxkeeper import __version__


def test_health_reports_ok(client: TestClient) -> None:
    resp = client.get("/api/health")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "version": __version__}
