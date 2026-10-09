"""CORS policy helpers with an explicit, local-development-only fallback."""
import logging
from typing import Iterable, List, Optional
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

LOCAL_DEVELOPMENT_ORIGINS = (
    'http://localhost:3000',
    'http://127.0.0.1:3000',
    'http://localhost:5173',
    'http://127.0.0.1:5173',
)


def resolve_cors_origins(origins: Optional[Iterable[str]]) -> List[str]:
    """Return explicit HTTP(S) origins only; invalid entries fail closed."""
    if origins is None:
        return list(LOCAL_DEVELOPMENT_ORIGINS)
    values = []
    for origin in origins:
        value = str(origin).strip().rstrip('/')
        parsed = urlsplit(value)
        valid = (
            value != '*'
            and parsed.scheme in {'http', 'https'}
            and bool(parsed.netloc)
            and not parsed.username
            and not parsed.password
            and not parsed.path
            and not parsed.query
            and not parsed.fragment
        )
        if valid:
            values.append(value)
        else:
            logger.error('Discarding invalid CORS origin configuration')
    return values
