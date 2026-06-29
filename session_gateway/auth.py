"""Autenticação bearer-token (comparação em tempo constante)."""
from __future__ import annotations

import secrets

from fastapi import Header, HTTPException

from . import config

_TOKEN = config.get_or_create_token()


async def require_token(authorization: str = Header(default="")) -> None:
    expected = f"Bearer {_TOKEN}"
    if not authorization or not secrets.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="invalid or missing bearer token")
