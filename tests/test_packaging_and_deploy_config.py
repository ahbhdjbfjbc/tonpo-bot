from pathlib import Path
import tomllib


ROOT = Path(__file__).parents[1]


def test_pyproject_includes_web_package_and_runtime_dependencies():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    includes = project["tool"]["setuptools"]["packages"]["find"]["include"]
    dependencies = project["project"]["dependencies"]
    dev_dependencies = project["project"]["optional-dependencies"]["dev"]
    assert "web*" in includes
    for dependency in ("fastapi", "uvicorn", "httpx", "python-multipart", "slowapi"):
        assert any(item.lower().startswith(dependency.lower()) for item in dependencies)
    assert sum(item.lower().startswith("pyjwt") for item in dependencies) == 1
    assert {"pytest==8.3.2", "pytest-asyncio==0.24.0", "pytest-cov==5.0.0"}.issubset(dev_dependencies)
    assert "services" in project["tool"]["coverage"]["run"]["source"]


def test_all_compose_database_urls_use_configured_postgres_user():
    compose = (ROOT / "docker-compose.yml").read_text()
    assert compose.count("postgresql://${POSTGRES_USER:-tonpo}:") == 3
    assert "postgresql://tonpo:${POSTGRES_PASSWORD}" not in compose
