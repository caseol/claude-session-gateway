"""Mecanismo secundário: sessões de terminal já abertas (resume/fork)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from .. import resume as resume_mod
from ..auth import require_token
from ..locks import SessionLock
from ..models import DiscoveredPromptReq, DiscoveredSession

router = APIRouter(prefix="/v1/discovered", tags=["discovered"],
                   dependencies=[Depends(require_token)])


@router.get("", response_model=list[DiscoveredSession])
async def list_discovered():
    return resume_mod.discover()


@router.post("/{session_id}/prompt")
async def prompt_discovered(session_id: str, req: DiscoveredPromptReq):
    if req.mode not in ("fork", "resume"):
        raise HTTPException(422, "mode deve ser 'fork' ou 'resume'")
    # fork não escreve no transcript original; resume exige lock + idle
    lock = SessionLock(session_id) if req.mode == "resume" else None
    if lock and not lock.acquire():
        raise HTTPException(409, "sessão travada por outro processo")
    try:
        result = await resume_mod.one_shot(
            session_id, req.prompt, mode=req.mode,
            permission_mode=req.permission_mode, lane=req.lane)
    except KeyError as e:
        raise HTTPException(404, str(e))
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except ValueError as e:
        raise HTTPException(422, str(e))
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    finally:
        if lock:
            lock.release()
    return result
