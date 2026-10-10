#!/usr/bin/env python3
"""Write a mode-0600 libpq service file from a URL held only in the environment."""
import os
import sys
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlsplit

ALLOWED_URL_ENV = {"DATABASE_URL", "RESTORE_DATABASE_URL"}
ALLOWED_QUERY_KEYS = {
    "application_name", "channel_binding", "connect_timeout", "host", "options",
    "port", "sslcert", "sslkey", "sslmode", "sslpassword", "sslrootcert",
    "target_session_attrs",
}


def _value(text: str) -> str:
    if any(ord(char) < 32 or ord(char) == 127 for char in text):
        raise ValueError("control characters are not allowed in PostgreSQL connection settings")
    if not text or any(char.isspace() or char in "#'\\\"" for char in text):
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return text


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[2] not in ALLOWED_URL_ENV:
        print("Usage: postgres_service_file.py OUTPUT_PATH DATABASE_URL|RESTORE_DATABASE_URL", file=sys.stderr)
        return 2

    raw_url = os.environ.get(sys.argv[2], "")
    try:
        parsed = urlsplit(raw_url)
        if parsed.scheme not in {"postgres", "postgresql", "postgresql+psycopg2", "postgresql+psycopg"}:
            raise ValueError("unsupported connection scheme")
        if not parsed.path and not parsed.hostname:
            raise ValueError("database name or host is required")
        params: dict[str, str] = {}
        if parsed.hostname:
            params["host"] = unquote(parsed.hostname)
        if parsed.port:
            params["port"] = str(parsed.port)
        if parsed.path.lstrip("/"):
            params["dbname"] = unquote(parsed.path.lstrip("/"))
        if parsed.username is not None:
            params["user"] = unquote(parsed.username)
        if parsed.password is not None:
            params["password"] = unquote(parsed.password)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True):
            if key not in ALLOWED_QUERY_KEYS:
                raise ValueError(f"unsupported connection option: {key}")
            params[key] = value
        if not params:
            raise ValueError("connection URL contains no usable settings")

        output = Path(sys.argv[1])
        content = "[tonpo_backup]\n" + "".join(f"{key}={_value(value)}\n" for key, value in params.items())
        output.write_text(content, encoding="utf-8")
        output.chmod(0o600)
        return 0
    except (ValueError, OSError) as exc:
        # Do not include the URL or any parsed credentials in diagnostics.
        print(f"Invalid PostgreSQL connection configuration: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
