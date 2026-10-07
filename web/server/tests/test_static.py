from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main
from app.main import create_app


HTML = "<!doctype html><html><head><title>Quality agent</title></head><body>UI</body></html>"
CSS = "body { color: navy; }"
JS = "console.log('quality agent');"
NOT_FOUND = {"error": {"code": "route_not_found", "message": "Route not found."}}
METHOD_NOT_ALLOWED = {
    "error": {"code": "method_not_allowed", "message": "Method not allowed."}
}


@pytest.fixture
def static_root(tmp_path):
    root = tmp_path / "static"
    assets = root / "assets"
    assets.mkdir(parents=True)
    (root / "index.html").write_text(HTML, encoding="utf-8")
    (assets / "app.css").write_text(CSS, encoding="utf-8")
    (assets / "app.js").write_text(JS, encoding="utf-8")
    return root


@pytest.mark.parametrize(
    "path",
    (
        "/",
        "/?fields=status",
        "/sessions/68df8b00aef4d8537282f001",
        "/sessions/not-an-object-id",
        "/sessions/%3Cscript%3E?fields=metadata",
    ),
)
def test_known_ui_paths_serve_fixed_html(static_root, path):
    with TestClient(create_app(static_root)) as client:
        response = client.get(path)
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/html; charset=utf-8"
    assert response.text == HTML


@pytest.mark.parametrize("path", ("/", "/sessions/example"))
def test_spa_html_requires_revalidation_and_rereads_replaced_index(static_root, path):
    with TestClient(create_app(static_root)) as client:
        response = client.get(path)
        assert response.headers["cache-control"] == "no-cache"
        updated = HTML.replace("UI", "Updated UI")
        (static_root / "index.html").write_text(updated, encoding="utf-8")
        response = client.get(path, headers={"If-None-Match": response.headers["etag"]})
        assert response.status_code == 200
        assert response.text == updated
        assert response.headers["cache-control"] == "no-cache"


@pytest.mark.parametrize(
    ("filename", "content", "media_types"),
    (
        ("app.css", CSS, {"text/css"}),
        ("app.js", JS, {"text/javascript", "application/javascript"}),
    ),
)
def test_assets_have_correct_content_and_mime_type(
    static_root, filename, content, media_types
):
    with TestClient(create_app(static_root)) as client:
        response = client.get(f"/assets/{filename}")
    assert response.status_code == 200
    assert response.headers["content-type"].split(";")[0] in media_types
    assert response.text == content


@pytest.mark.parametrize(
    "path",
    (
        "/assets/missing.js",
        "/assets/missing.css",
        "/assets",
        "/assets/",
        "/assets/nested",
        "/assets/nested/",
        "/unknown",
        "/sessions",
        "/sessions/",
        "/sessions/example/",
        "/sessions/example/runs",
        "/sessions/example/nested/path",
        "/index.html",
        "/ui/api/sessions",
        "/ui/api/sessions/example",
        "/v1/sessions",
        "/v1/sessions/example",
        "/healthz/",
        "/docs",
        "/redoc",
        "/openapi.json",
    ),
)
def test_missing_assets_and_unknown_paths_never_fall_back_or_redirect(static_root, path):
    nested = static_root / "assets" / "nested"
    nested.mkdir()
    (nested / "index.html").write_text(HTML)
    (static_root / "assets" / "404.html").write_text(HTML)
    with TestClient(create_app(static_root), follow_redirects=False) as client:
        response = client.get(path)
    assert response.status_code == 404
    assert response.json() == NOT_FOUND
    assert "location" not in response.headers


@pytest.mark.parametrize("index_state", ("missing", "directory"))
def test_missing_index_is_404_while_assets_and_health_work(static_root, index_state):
    index = static_root / "index.html"
    index.unlink()
    if index_state == "directory":
        index.mkdir()
    with TestClient(create_app(static_root)) as client:
        for path in ("/", "/sessions/not-an-object-id"):
            response = client.get(path)
            assert response.status_code == 404
            assert response.json() == NOT_FOUND
        assert client.get("/assets/app.js").text == JS
        assert client.get("/healthz").json() == {"status": "ok"}


def test_html_and_health_work_without_an_assets_directory(tmp_path):
    (tmp_path / "index.html").write_text(HTML)
    with TestClient(create_app(tmp_path)) as client:
        assert client.get("/").text == HTML
        assert client.get("/healthz").json() == {"status": "ok"}
        response = client.get("/assets/missing.js")
        assert response.status_code == 404
        assert response.json() == NOT_FOUND


def test_relative_root_is_resolved_before_working_directory_changes(static_root, monkeypatch):
    monkeypatch.chdir(static_root.parent)
    app = create_app(Path("static"))
    monkeypatch.chdir(static_root / "assets")
    with TestClient(app) as client:
        assert client.get("/").text == HTML
        assert client.get("/assets/app.js").text == JS


def test_default_root_is_relative_to_the_package(static_root, monkeypatch):
    monkeypatch.setattr(main, "__file__", str(static_root.parent / "app" / "main.py"))
    monkeypatch.chdir(static_root / "assets")
    with TestClient(create_app()) as client:
        assert client.get("/").text == HTML
        assert client.get("/assets/app.css").text == CSS


@pytest.mark.parametrize(
    "path",
    (
        "/assets/%2e%2e/index.html",
        "/assets/%2e%2e%2findex.html",
        "/assets/%2e%2e/%2e%2e/private.txt",
        "/assets/%2e%2e%2f%2e%2e%2fprivate.txt",
        "/assets/%2e%2e/assets-private/private.txt",
        "/sessions/example%2fnested",
    ),
)
def test_encoded_traversal_cannot_escape_assets_or_expand_ui_routes(static_root, path):
    (static_root.parent / "private.txt").write_text("outside the static root")
    sibling = static_root / "assets-private"
    sibling.mkdir()
    (sibling / "private.txt").write_text("outside the assets root")
    with TestClient(create_app(static_root), follow_redirects=False) as client:
        response = client.get(path)
    assert response.status_code == 404
    assert response.json() == NOT_FOUND


@pytest.mark.parametrize("link_kind", ("file", "directory", "index", "assets_root"))
def test_symlinks_cannot_escape_static_roots(static_root, link_kind):
    outside = static_root.parent / "private"
    outside.mkdir()
    secret = outside / "private.txt"
    secret.write_text("must not be served")
    if link_kind == "file":
        (static_root / "assets" / "private.txt").symlink_to(secret)
        paths = ("/assets/private.txt",)
    elif link_kind == "directory":
        (static_root / "assets" / "private").symlink_to(outside, target_is_directory=True)
        paths = ("/assets/private/private.txt",)
    elif link_kind == "index":
        (static_root / "index.html").unlink()
        (static_root / "index.html").symlink_to(secret)
        paths = ("/", "/sessions/not-an-object-id")
    else:
        (static_root / "assets").rename(static_root / "original-assets")
        (static_root / "assets").symlink_to(outside, target_is_directory=True)
        paths = ("/assets/private.txt",)
    with TestClient(create_app(static_root)) as client:
        for path in paths:
            response = client.get(path)
            assert response.status_code == 404
            assert response.json() == NOT_FOUND
        assert client.get("/healthz").json() == {"status": "ok"}


@pytest.mark.parametrize("path", ("/", "/sessions/not-an-object-id", "/healthz", "/assets/app.js"))
@pytest.mark.parametrize("method", ("POST", "PUT", "PATCH", "DELETE", "OPTIONS"))
def test_unsupported_methods_preserve_safe_errors_and_allow(static_root, path, method):
    with TestClient(create_app(static_root)) as client:
        response = client.request(method, path)
    assert response.status_code == 405
    assert response.json() == METHOD_NOT_ALLOWED
    expected = {"GET", "HEAD"} if path.startswith("/assets/") else {"GET"}
    assert {method.strip() for method in response.headers["allow"].split(",")} == expected


@pytest.mark.parametrize("path", ("/", "/sessions/not-an-object-id"))
def test_ui_routes_are_get_only(static_root, path):
    with TestClient(create_app(static_root)) as client:
        response = client.head(path)
    assert response.status_code == 405
    assert response.headers["allow"] == "GET"
    assert response.content == b""


def test_asset_head_returns_headers_without_a_body(static_root):
    with TestClient(create_app(static_root)) as client:
        response = client.head("/assets/app.css")
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/css; charset=utf-8"
    assert response.headers["content-length"] == str(len(CSS))
    assert response.content == b""
