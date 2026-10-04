"""
Run the Tonpo Web Platform (API + SPA).

Usage:
  python -m web.run
  # or
  uvicorn web.app:app --host 0.0.0.0 --port 8000 --reload

Requires the same environment variables as the bot (.env).
TRADING_DRY_RUN remains true unless explicitly changed in the environment.
"""
from __future__ import annotations

import logging
import os
import sys

# Ensure project root is on path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("web.run")


def main():
    import uvicorn
    from config.settings import settings

    host = os.getenv("WEB_HOST", "0.0.0.0")
    port = int(os.getenv("WEB_PORT", "8000"))
    logger.info(
        "Starting Tonpo Web on %s:%s (DRY_RUN=%s)",
        host, port, getattr(settings, "TRADING_DRY_RUN", True),
    )
    uvicorn.run(
        "web.app:app",
        host=host,
        port=port,
        reload=os.getenv("WEB_RELOAD", "false").lower() == "true",
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
    )


if __name__ == "__main__":
    main()
