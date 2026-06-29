"""Listagem de lanes + saúde dos proxies upstream."""
from __future__ import annotations

import socket

from fastapi import APIRouter, Depends

from ..auth import require_token
from ..lanes import LANES

router = APIRouter(prefix="/v1", tags=["lanes"], dependencies=[Depends(require_token)])


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


@router.get("/lanes")
async def list_lanes():
    out = []
    for name, lane in LANES.items():
        out.append({
            "lane": name,
            "command": lane.command,
            "proxy_port": lane.proxy_port,
            "proxy_up": _port_open(lane.proxy_port) if lane.proxy_port else None,
        })
    return out
