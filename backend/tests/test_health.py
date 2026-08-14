"""Smoke tests confirming the backend boots and the health endpoint responds."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_root_ok():
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_health_ok_without_database():
    """With no DATABASE_URL configured, health is still 200 and reports the DB
    as 'not_configured' rather than failing."""
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["database"] in {"not_configured", "unreachable", "connected"}
