from contextlib import asynccontextmanager
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_health_is_liveness_and_framework_errors_are_preserved(monkeypatch):
    events = []

    @asynccontextmanager
    async def fake_runtime(uri, database_name):
        events.append("startup")
        yield SimpleNamespace(sessions=None, runs=None)
        events.append("shutdown")

    monkeypatch.setattr("app.main.mongo_runtime", fake_runtime)
    settings = Settings(mongo_uri="mongodb://unit-test.invalid", mongo_db_name="unit")
    with TestClient(create_app(settings)) as client:
        for _ in range(2):
            response = client.get("/healthz")
            assert response.status_code == 200
            assert response.json() == {"status": "ok"}
        assert events == ["startup"]
        assert client.get("/docs").status_code == 404
        assert client.get("/unknown").json() == {
            "error": {"code": "route_not_found", "message": "Route not found."}
        }
        response = client.post("/healthz")
        assert response.status_code == 405
        assert "GET" in response.headers["allow"]
        assert response.json()["error"]["code"] == "method_not_allowed"
    assert events == ["startup", "shutdown"]
