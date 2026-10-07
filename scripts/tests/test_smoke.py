"""Exercise smoke checks against HTTP fixtures, without an API or database."""

import copy
import importlib.util
import io
import json
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from http.client import IncompleteRead
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError


spec = importlib.util.spec_from_file_location("smoke", Path(__file__).resolve().parents[1] / "smoke.py")
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)

SELECTED = "/v1/sessions?fields=started_at&fields=metadata.invoked_by.name&fields=metadata.boundary"
IDS = "/v1/sessions?fields=session_id"
INVALID = "/v1/sessions?fields=runs"
SESSION_ID = "68df8b00aef4d8537282f001"
OTHER_ID = "68df8b00aef4d8537282f099"
JS = "/assets/index-Bs7_9abc.js"
CSS = "/assets/index-Cdef0123.css"
HTML = (
    '<!doctype html><html><head><link rel="stylesheet" href="' + CSS + '"></head>'
    '<body><div id="root"></div><script crossorigin src="' + JS + '" type="module"></script></body></html>'
)


def response(body, status=200, mime="text/html; charset=utf-8", headers=None):
    if isinstance(body, str):
        body = body.encode("utf-8")
    return status, mime, body, headers or {}


def json_response(body, status=200):
    return response(json.dumps(body), status, "application/json; charset=utf-8")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.requests.append((self.command, self.path, self.headers.get("Content-Length")))
        status, mime, body, headers = self.server.routes.get(self.path, response("Unconfigured fixture", 500))
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        for name, value in headers.items():
            self.send_header(name, value)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    do_POST = do_PATCH = do_PUT = do_DELETE = do_GET

    def log_message(self, format, *args):
        pass


class SmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.base_url = "http://127.0.0.1:" + str(cls.server.server_port)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.thread.join()
        cls.server.server_close()

    def setUp(self):
        self.server.requests = []
        self.server.routes = {
            "/": response(HTML),
            JS: response("console.log('fixture');", mime="text/javascript; charset=utf-8"),
            CSS: response("body { color: black; }", mime="text/css"),
            "/sessions/000000000000000000000000": response(HTML),
            SELECTED: json_response([]),
            IDS: json_response([]),
            INVALID: json_response({"error": {"code": "invalid_field", "message": "A request field is invalid."}}, 400),
            "/v1/__smoke_missing__": json_response({"error": {"code": "route_not_found", "message": "Route not found."}}, 404),
        }
        for path in (
            "/assets/__smoke_missing__.js", "/assets/__smoke_missing__.css",
            "/__smoke_missing__", "/ui/api/sessions", "/healthz",
        ):
            self.server.routes[path] = response("<html>Not found</html>", 404)

    def invoke(self, base_url=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = smoke.main(["--base-url", base_url or self.base_url])
        return result, stdout.getvalue() + stderr.getvalue()

    def assert_failure(self, label, forbidden=()):
        result, output = self.invoke()
        self.assertEqual(result, 1)
        self.assertIn("FAIL " + label, output)
        self.assertNotIn("PASS smoke checks", output)
        for value in forbidden:
            self.assertNotIn(value, output)

    def populated(self):
        detail = {
            "session_id": SESSION_ID, "schema_version": 1,
            "started_at": "2026-10-01T09:07:04.000Z", "received_at": "2026-10-01T09:07:05.123Z",
            "status": "COMPLETED", "completion_time": None, "last_step_executed": [],
            "execution_outcome": None,
            "metadata": {"private-key": {"name": "Private Person", "token": "private-secret"}},
            "runs": [{
                "run_id": "68df8b00aef4d8537282f002", "session_id": SESSION_ID, "schema_version": 1,
                "step": "private-step", "command": "private-command", "verdict": "CUSTOM",
                "occurred_at": "2026-10-01T09:17:58.000Z", "received_at": "2026-10-01T09:17:59.456Z",
                "details": {"$data.key": [None, "private-secret"]},
            }],
        }
        self.server.routes[SELECTED] = json_response([{
            "session_id": SESSION_ID, "started_at": "2026-09-01T09:07:04.000Z", "metadata": {},
        }])
        # A concurrent insert can change the independently read ID-only list.
        self.server.routes[IDS] = json_response([{"session_id": OTHER_ID}, {"session_id": SESSION_ID}])
        self.server.routes["/sessions/" + SESSION_ID] = response(HTML)
        self.server.routes["/v1/sessions/" + SESSION_ID] = json_response(detail)
        return detail

    def test_empty_dataset_passes_all_get_checks_including_html_edge_404(self):
        result, output = self.invoke(self.base_url + "/")
        self.assertEqual(result, 0, output)
        self.assertIn("PASS smoke checks", output)
        self.assertEqual({path for _, path, _ in self.server.requests}, set(self.server.routes))
        self.assertEqual(len(self.server.requests), len(self.server.routes))
        self.assertTrue(all(method == "GET" and length is None for method, _, length in self.server.requests))

    def test_populated_dataset_checks_detail_without_snapshot_comparisons_or_data_logging(self):
        self.populated()
        result, output = self.invoke()
        self.assertEqual(result, 0, output)
        self.assertIn("Session detail: HTTP 200", output)
        for private in (SESSION_ID, OTHER_ID, "Private Person", "private-key", "private-secret", "$data.key", "private-command"):
            self.assertNotIn(private, output)

    def test_session_appearing_between_lists_still_gets_detail(self):
        detail = self.populated()
        detail["runs"] = []
        self.server.routes[SELECTED] = json_response([])
        self.server.routes[IDS] = json_response([{"session_id": SESSION_ID}])
        self.server.routes["/v1/sessions/" + SESSION_ID] = json_response(detail)
        result, output = self.invoke()
        self.assertEqual(result, 0, output)
        self.assertIn("Session detail: HTTP 200", output)

    def test_root_404_is_not_success(self):
        self.server.routes["/"] = response(HTML, 404)
        self.assert_failure("UI root")

    def test_root_requires_html_and_real_react_asset_elements(self):
        cases = (
            response(HTML, mime="application/json"),
            response(HTML.replace('<div id="root"></div>', "")),
            response(HTML.replace('type="module"', 'type="text/javascript"')),
            response(HTML.replace('rel="stylesheet"', 'rel="preload"')),
            response("<!-- " + HTML + " -->"),
            response(HTML + '<base href="https://example.invalid/">'),
            response(b"\xff"),
        )
        for fixture in cases:
            with self.subTest(fixture=cases.index(fixture)):
                self.server.routes["/"] = fixture
                self.assert_failure("UI root")

    def test_discovered_assets_require_200_matching_mime_and_nonempty_content(self):
        for path in (JS, CSS):
            good = self.server.routes[path]
            for fixture in (response("missing", 404), response(HTML), response(b"", mime=good[1]), response("  \n", mime=good[1])):
                with self.subTest(path=path, status=fixture[0], mime=fixture[1]):
                    self.server.routes[path] = fixture
                    self.assert_failure("JavaScript asset" if path == JS else "Stylesheet asset")
            self.server.routes[path] = good

    def test_html_parser_discovers_new_hashes_and_same_origin_absolute_urls(self):
        new_js, new_css = "/assets/other-abcdef.js", "/assets/other-fedcba.css"
        html = HTML.replace(JS, self.base_url + new_js).replace(CSS, new_css)
        self.server.routes["/"] = response(html)
        self.server.routes["/sessions/000000000000000000000000"] = response(html)
        self.server.routes[new_js] = response("export {};", mime="application/javascript")
        self.server.routes[new_css] = response("body {}", mime="text/css; charset=utf-8")
        result, output = self.invoke()
        self.assertEqual(result, 0, output)
        paths = [path for _, path, _ in self.server.requests]
        self.assertIn(new_js, paths)
        self.assertIn(new_css, paths)
        self.assertNotIn(JS, paths)
        self.assertNotIn(CSS, paths)

    def test_unsafe_asset_urls_are_never_requested_or_logged(self):
        for reference in (
            "https://example.invalid/assets/private-secret.js", "//example.invalid/assets/private-secret.js",
            self.base_url.replace("http://", "http://user:private-secret@") + JS,
            "/src/private-secret.tsx", "/assets/../../private-secret.js",
            "/assets/%2e%2e/private-secret.js", "assets/private-secret.js", JS + "?token=private-secret", "",
        ):
            with self.subTest(reference=reference):
                self.server.requests = []
                self.server.routes["/"] = response(HTML.replace(JS, reference))
                self.assert_failure("SPA asset references", ("private-secret", "example.invalid"))
                self.assertEqual([path for _, path, _ in self.server.requests], ["/"])

    def test_redirects_fail_without_following_even_if_destination_would_pass(self):
        for path, label in (("/", "UI root"), (JS, "JavaScript asset"), (SELECTED, "Selected list"), ("/healthz", "Edge health route")):
            original = self.server.routes[path]
            self.server.routes["/redirect-target?private-secret"] = original
            for status in (301, 302, 303, 307, 308):
                with self.subTest(path=path, status=status):
                    self.server.requests = []
                    self.server.routes[path] = response("private-secret", status, headers={"Location": "/redirect-target?private-secret"})
                    self.assert_failure(label, ("private-secret", "redirect-target"))
                    paths = [request[1] for request in self.server.requests]
                    self.assertEqual(paths.count(path), 1)
                    self.assertFalse(any(p.startswith("/redirect-target") for p in paths))
            self.server.routes[path] = original

    def test_old_api_ignoring_invalid_fields_fails_even_on_empty_database(self):
        self.server.routes[INVALID] = json_response([])
        self.assert_failure("Invalid list selector")

    def test_selected_list_requires_array_valid_ids_and_selected_roots(self):
        for payload in (
            {}, None, "private-secret", [None], [{}], [{"session_id": "https://example.invalid/private-secret"}],
            [{"session_id": SESSION_ID, "runs": []}], [{"session_id": SESSION_ID, "private-key": "private-secret"}],
            [{"session_id": SESSION_ID, "status": "COMPLETED"}],
            [{"session_id": SESSION_ID, "started_at": None}], [{"session_id": SESSION_ID, "metadata": []}],
        ):
            with self.subTest(payload=payload):
                self.server.routes[SELECTED] = json_response(payload)
                self.assert_failure("Selected list", ("private-key", "private-secret", "example.invalid"))

    def test_selected_values_can_be_missing_null_or_nonobject_intermediates(self):
        self.populated()
        for row in (
            {"session_id": SESSION_ID},
            {"session_id": SESSION_ID, "metadata": {}},
            {"session_id": SESSION_ID, "metadata": {"boundary": None, "invoked_by": [{"name": None}, {}]}},
            {"session_id": SESSION_ID, "metadata": {"invoked_by": "arbitrary-value"}},
        ):
            with self.subTest(row=row):
                self.server.routes[SELECTED] = json_response([row])
                result, output = self.invoke()
                self.assertEqual(result, 0, output)

    def test_id_only_list_rejects_extra_fields(self):
        self.server.routes[IDS] = json_response([{"session_id": SESSION_ID, "metadata": {}}])
        self.assert_failure("ID-only list")

    def test_timestamps_match_the_browser_contract(self):
        detail = self.populated()
        for invalid in (
            "2026-10-01T09:07:04Z", "2026-10-01T09:07:04.123456Z",
            "2026-10-01T09:07:04.123+00:00", "2026-02-30T09:07:04.123Z",
            "2026-13-01T09:07:04.123Z", "private-secret",
        ):
            for target in ("selected", "started_at", "received_at", "completion_time", "run_occurred_at", "run_received_at"):
                with self.subTest(target=target, value=invalid):
                    changed = copy.deepcopy(detail)
                    self.server.routes[SELECTED] = json_response([{"session_id": SESSION_ID}])
                    if target == "selected":
                        self.server.routes[SELECTED] = json_response([{"session_id": SESSION_ID, "started_at": invalid}])
                    elif target.startswith("run_"):
                        changed["runs"][0][target[4:]] = invalid
                    else:
                        changed[target] = invalid
                    self.server.routes["/v1/sessions/" + SESSION_ID] = json_response(changed)
                    self.assert_failure("Selected list" if target == "selected" else "Session detail", ("private-secret",))

    def test_api_responses_require_json_mime_and_parseable_json(self):
        for path, label in ((SELECTED, "Selected list"), (INVALID, "Invalid list selector"), ("/v1/__smoke_missing__", "Unknown API route")):
            good = self.server.routes[path]
            for fixture in (response("private-secret", good[0]), response(b"\xffprivate-secret", good[0], "application/json")):
                with self.subTest(path=path, mime=fixture[1]):
                    self.server.routes[path] = fixture
                    self.assert_failure(label, ("private-secret",))
            self.server.routes[path] = good

    def test_api_errors_require_expected_envelope_and_code(self):
        for path, status, label in ((INVALID, 400, "Invalid list selector"), ("/v1/__smoke_missing__", 404, "Unknown API route")):
            good = self.server.routes[path]
            for payload in ({"detail": "private-secret"}, {"error": {"code": "private-code", "message": "private-secret"}}, []):
                with self.subTest(path=path, payload=payload):
                    self.server.routes[path] = json_response(payload, status)
                    self.assert_failure(label, ("private-secret", "private-code"))
            self.server.routes[path] = good

    def test_ui_detail_must_match_root_spa(self):
        self.server.routes["/sessions/000000000000000000000000"] = response(HTML + "different")
        self.assert_failure("UI session route")

    def test_full_detail_requires_metadata_runs_and_complete_run_shape(self):
        original = self.populated()
        variants = []
        for key in ("metadata", "runs", "received_at"):
            detail = copy.deepcopy(original)
            del detail[key]
            variants.append(detail)
        for key, value in (("metadata", None), ("runs", {}), ("session_id", OTHER_ID), ("schema_version", True)):
            variants.append(dict(original, **{key: value}))
        detail = copy.deepcopy(original)
        del detail["runs"][0]["details"]
        variants.append(detail)
        detail = copy.deepcopy(original)
        detail["runs"][0]["details"] = []
        variants.append(detail)
        for index, detail in enumerate(variants):
            with self.subTest(variant=index):
                self.server.routes["/v1/sessions/" + SESSION_ID] = json_response(detail)
                self.assert_failure("Session detail", ("private-key", "Private Person", "private-secret"))

    def test_missing_routes_cannot_fall_back_to_successful_spa(self):
        for path, label in (
            ("/assets/__smoke_missing__.js", "Missing JavaScript asset"),
            ("/assets/__smoke_missing__.css", "Missing stylesheet asset"),
            ("/__smoke_missing__", "Unknown UI route"),
            ("/ui/api/sessions", "Legacy UI API route"),
            ("/healthz", "Edge health route"),
            ("/v1/__smoke_missing__", "Unknown API route"),
        ):
            good = self.server.routes[path]
            with self.subTest(path=path):
                self.server.routes[path] = response(HTML)
                self.assert_failure(label)
            self.server.routes[path] = good

    def test_invalid_base_urls_fail_safely_before_network_access(self):
        for base in (
            "https://example.invalid", "file:///private-secret", "http://user:private-secret@example.invalid",
            self.base_url + "/private-secret", self.base_url + "?private-secret", self.base_url + "#private-secret",
            self.base_url + "?", self.base_url + "#", "http://localhost:bad", "http://localhost:65536",
            "http://localhost:0", "http://localhost:", "http://[bad", "http://", "localhost:8080",
            "http://local\nhost", " http://localhost", "http://localhost\\private-secret",
        ):
            with self.subTest(base=base), patch.object(smoke, "build_opener") as opener:
                result, output = self.invoke(base)
                self.assertEqual(result, 1)
                self.assertIn("FAIL Base URL", output)
                self.assertNotIn("private-secret", output)
                opener.assert_not_called()

    def test_network_and_read_failures_are_sanitized_without_retry(self):
        for error in (URLError("private-secret"), TimeoutError("private-secret"), IncompleteRead(b"private-secret")):
            for stage in ("open", "read"):
                with self.subTest(error=type(error).__name__, stage=stage), patch.object(smoke, "build_opener") as factory:
                    if stage == "open":
                        factory.return_value.open.side_effect = error
                    else:
                        reply = factory.return_value.open.return_value
                        reply.code = 200
                        reply.headers.get_content_type.return_value = "text/html"
                        reply.read.side_effect = error
                    self.assert_failure("UI root", ("private-secret", "Traceback"))
                    factory.return_value.open.assert_called_once()


if __name__ == "__main__":
    unittest.main()
