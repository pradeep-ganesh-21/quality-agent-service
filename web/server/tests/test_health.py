from fastapi.testclient import TestClient

from app.main import create_app


def test_health_is_liveness_and_no_ui_or_data_routes_exist_yet():
    app = create_app()
    with TestClient(app) as client:
        upstream = app.state.api_client
        assert not upstream.is_closed
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        for path in ("/", "/ui/api/sessions", "/assets/missing.js", "/unknown"):
            response = client.get(path)
            assert response.status_code == 404
            assert response.json()["error"]["code"] == "route_not_found"
        response = client.post("/healthz")
        assert response.status_code == 405
        assert "GET" in response.headers["allow"]
    assert upstream.is_closed
