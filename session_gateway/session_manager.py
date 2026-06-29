"""Registry e ciclo de vida das sessões persistentes hospedadas pelo gateway."""
from __future__ import annotations

import asyncio
import os
import uuid
from typing import Optional

from . import config
from .child import PersistentClaudeChild
from .lanes import get_lane
from .models import CreateSessionReq, SessionInfo


class SessionManager:
    def __init__(self) -> None:
        self._children: dict[str, PersistentClaudeChild] = {}
        self._lock = asyncio.Lock()

    async def create(self, req: CreateSessionReq) -> PersistentClaudeChild:
        lane = get_lane(req.lane)
        cwd = req.cwd or os.path.expanduser("~/Workspace")
        if not config.cwd_allowed(cwd):
            raise PermissionError(f"cwd fora das raízes permitidas: {cwd}")
        os.makedirs(cwd, exist_ok=True)

        mode = req.permission_mode or config.DEFAULT_PERMISSION_MODE
        _validate_mode(mode)

        sid = req.session_id if getattr(req, "session_id", None) else str(uuid.uuid4())
        child = PersistentClaudeChild(
            lane=lane, session_id=sid, cwd=cwd, model=req.model,
            create_permission_mode=mode, mcp_config=req.mcp_config)
        await child.start(resume=False)
        async with self._lock:
            self._children[child.session_id] = child
        return child

    def get(self, session_id: str) -> Optional[PersistentClaudeChild]:
        return self._children.get(session_id)

    def list(self) -> list[SessionInfo]:
        return [self._info(c) for c in self._children.values()]

    async def stop(self, session_id: str) -> bool:
        child = self._children.pop(session_id, None)
        if not child:
            return False
        await child.stop()
        return True

    async def stop_all(self) -> None:
        for c in list(self._children.values()):
            await c.stop()
        self._children.clear()

    @staticmethod
    def _info(c: PersistentClaudeChild) -> SessionInfo:
        return SessionInfo(
            session_id=c.session_id, lane=c.lane.name, cwd=c.cwd, status=c.status,
            transcript_path=c.transcript_path, started_at=c.started_at,
            last_turn_at=c.last_turn_at)

    def info(self, c: PersistentClaudeChild) -> SessionInfo:
        return self._info(c)


def _validate_mode(mode: str) -> None:
    if mode not in config.VALID_PERMISSION_MODES:
        raise ValueError(f"permission_mode inválido: {mode}")
    if mode in config.DANGEROUS_MODES and not config.ALLOW_DANGEROUS_MODES:
        raise PermissionError(
            f"modo '{mode}' bloqueado (GW_ALLOW_DANGEROUS_MODES != 1)")


MANAGER = SessionManager()
