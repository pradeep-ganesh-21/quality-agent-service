"""Create local Compose credentials once, without printing or overwriting them."""

import os
from pathlib import Path
import secrets
from urllib.parse import quote


def main() -> None:
    target = Path(__file__).resolve().parents[1] / ".env"
    app_password = secrets.token_hex(24)
    root_password = secrets.token_hex(24)
    values = {
        "MONGO_DB_NAME": "quality_agent",
        "MONGO_INITDB_ROOT_USERNAME": "quality_agent_root",
        "MONGO_INITDB_ROOT_PASSWORD": root_password,
        "MONGO_APP_USERNAME": "quality_agent_app",
        "MONGO_APP_PASSWORD": app_password,
        "MONGO_URI": (
            f"mongodb://quality_agent_app:{quote(app_password, safe='')}"
            "@mongo:27017/quality_agent?authSource=quality_agent"
        ),
        "API_BASE_URL": "http://api:8000",
    }
    try:
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        print("Existing .env retained; no credentials changed.")
        return
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write("# Local generated credentials. Do not commit or share.\n")
        for name, value in values.items():
            handle.write(f"{name}={value}\n")
    print("Created private .env with local credentials (mode 0600).")


if __name__ == "__main__":
    main()
