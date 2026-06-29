"""Entrypoint uvicorn (bind 127.0.0.1)."""
from __future__ import annotations

import uvicorn

from . import config


def main() -> None:
    config.ensure_dirs()
    token = config.get_or_create_token()
    print(f"Session Gateway em http://{config.HOST}:{config.PORT}")
    print(f"Bearer token: {config.TOKEN_FILE} ({token[:8]}...)")
    print(f"allow_dangerous_modes={config.ALLOW_DANGEROUS_MODES}")
    uvicorn.run("session_gateway.app:app", host=config.HOST, port=config.PORT,
                log_level="warning")


if __name__ == "__main__":
    main()
