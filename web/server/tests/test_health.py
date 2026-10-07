import socket

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app


def test_health_is_liveness_and_framework_errors_are_preserved(tmp_path):
    with TestClient(create_app(tmp_path / "missing-build")) as client:
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        response = client.post("/healthz")
        assert response.status_code == 405
        assert "GET" in response.headers["allow"]
        assert response.json()["error"]["code"] == "method_not_allowed"


@pytest.mark.parametrize(
    "path",
    (
        "/",
        "/sessions/68df8b00aef4d8537282f001",
        "/ui/api/sessions",
        "/ui/api/sessions/68df8b00aef4d8537282f001",
        "/v1/sessions",
        "/assets/missing.js",
        "/unknown",
        "/docs",
    ),
)
def test_missing_build_and_unknown_routes_return_404(path, tmp_path):
    with TestClient(create_app(tmp_path / "missing-build")) as client:
        response = client.get(path)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "route_not_found"


@pytest.mark.parametrize("with_build", (False, True))
def test_startup_and_requests_need_no_outbound_client_or_connection(
    monkeypatch, tmp_path, with_build
):
    static_root = tmp_path / "static"
    if with_build:
        (static_root / "assets").mkdir(parents=True)
        (static_root / "index.html").write_text("<!doctype html><title>UI</title>")
        (static_root / "assets" / "app.js").write_text("console.log('UI');")

    def reject_outbound_io(*args, **kwargs):
        pytest.fail("The webserver must not create an outbound client or connection.")

    monkeypatch.setattr(httpx.AsyncClient, "__init__", reject_outbound_io)
    monkeypatch.setattr(httpx.HTTPTransport, "__init__", reject_outbound_io)
    monkeypatch.setattr(socket, "create_connection", reject_outbound_io)
    monkeypatch.setattr(socket.socket, "connect", reject_outbound_io)

    with TestClient(create_app(static_root)) as client:
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        if with_build:
            for path in ("/", "/sessions/not-an-object-id", "/assets/app.js"):
                assert client.get(path).status_code == 200
