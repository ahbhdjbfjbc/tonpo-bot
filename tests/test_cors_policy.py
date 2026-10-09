from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from web.cors import LOCAL_DEVELOPMENT_ORIGINS, resolve_cors_origins


def test_cors_defaults_to_explicit_local_development_origins():
    assert resolve_cors_origins(None) == list(LOCAL_DEVELOPMENT_ORIGINS)
    assert '*' not in resolve_cors_origins(None)


def test_cors_discards_wildcard_and_preserves_configured_origins():
    assert resolve_cors_origins(['*', 'https://dashboard.example.test']) == [
        'https://dashboard.example.test'
    ]
    assert resolve_cors_origins(['*']) == []


def test_cors_discards_origins_with_paths_or_credentials():
    assert resolve_cors_origins([
        'https://dashboard.example.test/app',
        'https://user:password@dashboard.example.test',
        'https://dashboard.example.test',
    ]) == ['https://dashboard.example.test']


def test_cors_preflight_allows_configured_origin_and_rejects_other_origin():
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolve_cors_origins(['http://localhost:5173']),
        allow_credentials=True,
        allow_methods=['GET'],
        allow_headers=['Authorization'],
    )

    @app.get('/health')
    def health():
        return {'status': 'ok'}

    client = TestClient(app)
    allowed = client.options(
        '/health',
        headers={
            'Origin': 'http://localhost:5173',
            'Access-Control-Request-Method': 'GET',
            'Access-Control-Request-Headers': 'Authorization',
        },
    )
    denied = client.options(
        '/health',
        headers={
            'Origin': 'https://untrusted.example.test',
            'Access-Control-Request-Method': 'GET',
        },
    )

    assert allowed.status_code == 200
    assert allowed.headers['access-control-allow-origin'] == 'http://localhost:5173'
    assert 'access-control-allow-origin' not in denied.headers
