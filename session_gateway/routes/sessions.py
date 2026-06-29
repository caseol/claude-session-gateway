"""CRUD de sessões persistentes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_token
from ..models import CreateSessionReq, SessionInfo
from ..session_manager import MANAGER

router = APIRouter(prefix="/v1/sessions", tags=["sessions"],
                   dependencies=[Depends(require_token)])


@router.post("", response_model=SessionInfo)
async def create_session(req: CreateSessionReq):
    try:
        child = await MANAGER.create(req)
    except KeyError as e:
        raise HTTPException(422, str(e))
    except (PermissionError,) as e:
        raise HTTPException(403, str(e))
    except ValueError as e:
        raise HTTPException(422, str(e))
    except RuntimeError as e:
        raise HTTPException(502, str(e))
    return MANAGER.info(child)


@router.get("", response_model=list[SessionInfo])
async def list_sessions():
    return MANAGER.list()


@router.get("/{session_id}", response_model=SessionInfo)
async def get_session(session_id: str):
    c = MANAGER.get(session_id)
    if not c:
        raise HTTPException(404, "sessão não encontrada")
    return MANAGER.info(c)


@router.delete("/{session_id}")
async def delete_session(session_id: str):
    ok = await MANAGER.stop(session_id)
    if not ok:
        raise HTTPException(404, "sessão não encontrada")
    return {"stopped": session_id}
