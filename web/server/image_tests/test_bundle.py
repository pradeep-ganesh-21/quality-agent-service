"""Run in the Docker test target, against assets inherited from the runtime image."""

import os
import shutil
from html.parser import HTMLParser
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


class BundleReferences(HTMLParser):
    def __init__(self):
        super().__init__()
        self.has_root = False
        self.scripts = []
        self.styles = []

    def handle_starttag(self, tag, attributes):
        attributes = dict(attributes)
        if tag == "div" and attributes.get("id") == "root":
            self.has_root = True
        if tag == "script" and attributes.get("type") == "module":
            self.scripts.append(attributes.get("src"))
        if tag == "link" and attributes.get("rel") == "stylesheet":
            self.styles.append(attributes.get("href"))


@pytest.fixture
def client():
    # No static_root override, temporary fixture, or host-mounted dist: a missing
    # image bundle must fail, even though the process health check still succeeds.
    with TestClient(create_app(), follow_redirects=False) as client:
        yield client


def test_runtime_bundle_serves_html_and_every_referenced_script_and_stylesheet(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "no-cache"
    page = BundleReferences()
    page.feed(response.text)
    assert page.has_root
    assert page.scripts and page.styles

    for references, media_types in (
        (page.scripts, {"text/javascript", "application/javascript"}),
        (page.styles, {"text/css"}),
    ):
        for reference in references:
            assert isinstance(reference, str) and reference.startswith("/assets/")
            parsed = urlsplit(reference)
            assert not parsed.scheme and not parsed.netloc
            asset = client.get(reference)
            assert asset.status_code == 200
            assert asset.headers["content-type"].split(";")[0] in media_types
            assert asset.content.strip()
            assert asset.content != response.content

    deep_link = client.get("/sessions/000000000000000000000000")
    assert deep_link.status_code == 200
    assert deep_link.content == response.content


@pytest.mark.parametrize("path", (
    "/assets/__missing_bundle_asset__.js", "/unknown", "/ui/api/sessions", "/v1/sessions",
))
def test_packaged_image_does_not_turn_missing_routes_into_html(client, path):
    assert client.get(path).status_code == 404


def test_packaged_image_health_is_internal_liveness(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_python_image_runs_nonroot_without_node_or_npm():
    assert os.getuid() != 0
    assert shutil.which("node") is None
    assert shutil.which("npm") is None
