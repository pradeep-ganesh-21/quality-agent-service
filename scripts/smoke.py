"""Read-only HTTP checks for the deployed React application and API routing."""

import argparse
import json
import re
import sys
from datetime import datetime
from html.parser import HTMLParser
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class SmokeFailure(Exception):
    """Contains only a static check label and a safe corrective reason."""


def require(condition, label, reason):
    if not condition:
        raise SmokeFailure(f"{label}: {reason}")


def validate_base_url(value):
    reason = "use an HTTP origin such as http://localhost:8080, without credentials, path, query, or fragment."
    try:
        parts = urlsplit(value)
        valid = (
            parts.scheme == "http"
            and parts.hostname
            and parts.username is None
            and parts.password is None
            and parts.path in ("", "/")
            and parts.port != 0
            and not parts.netloc.endswith(":")
            and not any(char in value for char in "?#\\%")
            and all(32 < ord(char) < 127 for char in value)
        )
    except ValueError:
        valid = False
    require(valid, "Base URL", reason)
    return "http://" + parts.netloc


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class SPAParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.root = False
        self.base = False
        self.scripts = []
        self.styles = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "div" and attrs.get("id") == "root":
            self.root = True
        if tag == "base":
            self.base = True
        if tag == "script" and (attrs.get("type") or "").lower() == "module":
            self.scripts.append(attrs.get("src") or "")
        if tag == "link" and "stylesheet" in (attrs.get("rel") or "").lower().split():
            self.styles.append(attrs.get("href") or "")


def asset_path(reference, base_url, extension):
    reason = "rebuild the SPA with same-origin /assets/ JavaScript and CSS references."
    try:
        origin = urlsplit(base_url)
        asset = urlsplit(urljoin(base_url + "/", reference))
        valid = (
            asset.scheme == origin.scheme
            and asset.hostname == origin.hostname
            and (asset.port if asset.port is not None else 80) == (origin.port if origin.port is not None else 80)
            and asset.username is None
            and asset.password is None
            and urlsplit(reference).path.startswith("/assets/")
            and not any(char in reference for char in "?#\\%")
            and all(32 < ord(char) < 127 for char in reference)
            and re.fullmatch(r"/assets/(?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_.-]+\." + extension, asset.path)
        )
    except ValueError:
        valid = False
    require(valid, "SPA asset references", reason)
    return asset.path


def valid_id(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{24}", value) is not None


def valid_timestamp(value):
    if not isinstance(value, str) or re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", value
    ) is None:
        return False
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return False
    return True


PAGE_FIELDS = {"items", "page_size", "total_count", "next_cursor", "previous_cursor"}


def check_list(value, id_only=False, label=None):
    label = label or ("ID-only list" if id_only else "Selected list")
    reason = "deploy the paginated field-selection API; expected a page envelope with only selected roots and valid session IDs."
    require(isinstance(value, dict) and set(value) == PAGE_FIELDS, label, reason)
    require(type(value["page_size"]) is int and 1 <= value["page_size"] <= 100, label, reason)
    require(type(value["total_count"]) is int and value["total_count"] >= 0, label, reason)
    for cursor in (value["next_cursor"], value["previous_cursor"]):
        require(
            cursor is None
            or (isinstance(cursor, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,512}", cursor)),
            label, reason,
        )
    rows = value["items"]
    require(isinstance(rows, list) and len(rows) <= value["page_size"], label, reason)
    allowed = {"session_id"} if id_only else {"session_id", "started_at", "metadata"}
    for row in rows:
        require(
            isinstance(row, dict)
            and set(row) <= allowed
            and valid_id(row.get("session_id"))
            and ("started_at" not in row or valid_timestamp(row["started_at"]))
            and ("metadata" not in row or isinstance(row["metadata"], dict)),
            label, reason,
        )
    return rows


def check_detail(value, session_id):
    fields = {
        "session_id", "schema_version", "started_at", "received_at", "status",
        "completion_time", "last_step_executed", "execution_outcome", "metadata", "runs",
    }
    reason = "deploy the full-detail API; expected all session roots, metadata object, and runs array."
    require(
        isinstance(value, dict)
        and set(value) == fields
        and value["session_id"] == session_id
        and type(value["schema_version"]) is int and value["schema_version"] == 1
        and valid_timestamp(value["started_at"])
        and valid_timestamp(value["received_at"])
        and value["status"] in ("IN_PROGRESS", "COMPLETED", "FAILED")
        and (value["completion_time"] is None or valid_timestamp(value["completion_time"]))
        and isinstance(value["last_step_executed"], list)
        and all(isinstance(step, str) for step in value["last_step_executed"])
        and (value["execution_outcome"] is None or isinstance(value["execution_outcome"], dict))
        and isinstance(value["metadata"], dict)
        and isinstance(value["runs"], list),
        "Session detail", reason,
    )
    run_fields = {
        "run_id", "session_id", "schema_version", "step", "command", "verdict",
        "occurred_at", "received_at", "details",
    }
    for run in value["runs"]:
        require(
            isinstance(run, dict)
            and set(run) == run_fields
            and valid_id(run["run_id"])
            and run["session_id"] == session_id
            and type(run["schema_version"]) is int and run["schema_version"] == 1
            and all(isinstance(run[key], str) and run[key]
                    for key in ("step", "command", "verdict"))
            and valid_timestamp(run["occurred_at"])
            and valid_timestamp(run["received_at"])
            and isinstance(run["details"], dict),
            "Session detail", "deploy the full-detail API; expected complete run objects with details objects.",
        )


def run_checks(base_url):
    base_url = validate_base_url(base_url)
    opener = build_opener(NoRedirects())

    def get(label, path, expected=200, media_types=()):
        try:
            try:
                response = opener.open(Request(base_url + path, method="GET"), timeout=5)
            except HTTPError as error:
                response = error
            with response:
                status = response.code
                print(f"{label}: HTTP {status}")
                require(not 300 <= status < 400, label,
                        "redirects are not allowed; check the HTTP origin and proxy routes.")
                require(status == expected, label,
                        f"expected HTTP {expected}; check deployed images and proxy routes.")
                require(not media_types or response.headers.get_content_type() in media_types,
                        label, "unexpected Content-Type; check asset serving and API proxy routing.")
                return response.read()
        except (URLError, OSError, HTTPException, ValueError):
            raise SmokeFailure(f"{label}: request failed; check the HTTP origin, service availability, and proxy routes.") from None

    def get_json(label, path, expected=200):
        body = get(label, path, expected, ("application/json",))
        try:
            return json.loads(body)
        except (ValueError, UnicodeError, RecursionError):
            raise SmokeFailure(f"{label}: invalid JSON; check the deployed API and proxy routing.") from None

    html = get("UI root", "/", media_types=("text/html",))
    page = SPAParser()
    try:
        page.feed(html.decode("utf-8"))
        page.close()
    except (UnicodeError, ValueError, AssertionError):
        raise SmokeFailure("UI root: invalid HTML; rebuild and serve the React bundle.") from None
    require(page.root and page.scripts and page.styles and not page.base, "UI root",
            "expected a React root, module script, and stylesheet without a base override; rebuild the React bundle.")
    for references, extension, label, media_types in (
        (page.scripts, "js", "JavaScript asset", ("text/javascript", "application/javascript")),
        (page.styles, "css", "Stylesheet asset", ("text/css",)),
    ):
        for reference in dict.fromkeys(references):
            body = get(label, asset_path(reference, base_url, extension), media_types=media_types)
            require(body.strip(), label, "empty asset; rebuild and serve the complete React bundle.")

    invalid_field = {"error": {"code": "invalid_field", "message": "A request field is invalid."}}
    selected = check_list(get_json("Selected list", "/v1/sessions?fields=started_at&fields=status&fields=metadata.invoked_by.email&fields=metadata.boundary"))
    ids = check_list(get_json("ID-only list", "/v1/sessions?fields=session_id"), id_only=True)
    check_list(
        get_json("Filtered list", "/v1/sessions?fields=session_id&status=COMPLETED&page_size=1"),
        id_only=True, label="Filtered list",
    )
    invalid = get_json("Invalid list selector", "/v1/sessions?fields=runs", 400)
    require(invalid == invalid_field,
            "Invalid list selector", "expected the invalid_field error envelope; deploy the field-selection API.")
    rejected = get_json("Invalid list parameter", "/v1/sessions?page_size=0", 400)
    require(rejected == invalid_field,
            "Invalid list parameter", "expected the invalid_field error envelope; deploy the paginated list API.")

    # Requests are independent reads: never compare counts, ordering, or mutable values.
    rows = selected or ids
    session_id = rows[0]["session_id"] if rows else "000000000000000000000000"
    detail_html = get("UI session route", "/sessions/" + session_id, media_types=("text/html",))
    require(detail_html == html, "UI session route", "expected the same SPA HTML as the root; check web routing.")
    if rows:
        detail = get_json("Session detail", "/v1/sessions/" + session_id)
        check_detail(detail, session_id)

    for label, path in (
        ("Missing JavaScript asset", "/assets/__smoke_missing__.js"),
        ("Missing stylesheet asset", "/assets/__smoke_missing__.css"),
        ("Unknown UI route", "/__smoke_missing__"),
        ("Legacy UI API route", "/ui/api/sessions"),
        ("Edge health route", "/healthz"),
    ):
        get(label, path, 404)
    missing = get_json("Unknown API route", "/v1/__smoke_missing__", 404)
    require(missing == {"error": {"code": "route_not_found", "message": "Route not found."}},
            "Unknown API route", "expected the route_not_found error envelope; check API proxy routing.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8080")
    arguments = parser.parse_args(argv)
    try:
        run_checks(arguments.base_url)
    except SmokeFailure as error:
        print(f"FAIL {error}", file=sys.stderr)
        return 1
    print("PASS smoke checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
