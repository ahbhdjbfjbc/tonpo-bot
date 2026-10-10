import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).parents[1]
HELPER = ROOT / "scripts" / "postgres_service_file.py"


def test_service_file_parses_sqlalchemy_uri_and_protects_credentials(tmp_path):
    path = tmp_path / "pg_service.conf"
    secret_url = "postgresql+psycopg2://tonpo:p%40ss%3Aword@db.example:5433/tonpo%20prod?sslmode=verify-full&application_name=tonpo%20backup"
    env = os.environ.copy()
    env["DATABASE_URL"] = secret_url

    result = subprocess.run(
        [sys.executable, str(HELPER), str(path), "DATABASE_URL"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert path.stat().st_mode & 0o777 == 0o600
    service = path.read_text()
    assert "[tonpo_backup]" in service
    assert "host=db.example" in service
    assert "port=5433" in service
    assert 'dbname="tonpo prod"' in service
    assert "user=tonpo" in service
    assert "password=p@ss:word" in service
    assert "sslmode=verify-full" in service
    assert 'application_name="tonpo backup"' in service
    assert secret_url not in service


def test_service_file_rejects_unknown_options_without_echoing_url_or_password(tmp_path):
    path = tmp_path / "pg_service.conf"
    secret_url = "postgresql://tonpo:topsecret@db.example/tonpo?unknown=topsecret"
    env = os.environ.copy()
    env["RESTORE_DATABASE_URL"] = secret_url

    result = subprocess.run(
        [sys.executable, str(HELPER), str(path), "RESTORE_DATABASE_URL"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "unsupported connection option" in result.stderr
    assert secret_url not in result.stderr
    assert "topsecret" not in result.stderr
    assert not path.exists()
