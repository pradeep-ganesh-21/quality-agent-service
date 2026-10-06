"""Non-destructive HTTP checks for infrastructure and proxy routing."""

import argparse
import json
from urllib.error import HTTPError
from urllib.request import urlopen


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8080")
    arguments = parser.parse_args()
    base_url = arguments.base_url.rstrip("/")
    for path in ("/healthz", "/v1/__smoke_missing__", "/", "/ui/api/sessions", "/assets/missing.js"):
        try:
            with urlopen(base_url + path, timeout=5) as response:
                status, body = response.status, response.read()
        except HTTPError as response:
            with response:
                status, body = response.code, response.read()
        if status != 404:
            raise SystemExit(f"FAIL {path}: expected 404, received {status}")
        if path != "/healthz" and json.loads(body) != {
            "error": {"code": "route_not_found", "message": "Route not found."}
        }:
            raise SystemExit(f"FAIL {path}: unexpected upstream error envelope")
        print(f"PASS {path}: 404 (expected)")


if __name__ == "__main__":
    main()
