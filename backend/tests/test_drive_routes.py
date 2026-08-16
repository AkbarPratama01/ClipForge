"""Google Drive route behavior that can be verified offline (no OAuth/network).

OAuth configuration is absent in the test environment and no MySQL server is
reachable, so these tests pin down the *degraded* paths: clear 4xx errors
instead of 500s, and graceful "not connected" status.
"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_connect_requires_oauth_config() -> None:
    resp = client.post("/api/google-drive/connect")
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"]["code"] == "GOOGLE_OAUTH_NOT_CONFIGURED"
    assert "GOOGLE_CLIENT_ID" in body["error"]["detail"]


def test_status_reports_disconnected_without_database() -> None:
    resp = client.get("/api/google-drive/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["connected"] is False


def test_list_files_degrades_when_database_down() -> None:
    resp = client.get("/api/google-drive/files")
    assert resp.status_code in (400, 503)
    body = resp.json()
    assert body["error"]["code"] in ("STORAGE_ERROR", "STORAGE_NOT_CONNECTED")


def test_bootstrap_degrades_when_database_down() -> None:
    resp = client.post("/api/google-drive/bootstrap")
    assert resp.status_code in (400, 503)
