"""SSE de tail do transcript de uma sessão (hospedada ou descoberta)."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from .. import resume as resume_mod
from ..auth import require_token
from ..session_manager import MANAGER
from ..watch import tail_transcript

router = APIRouter(prefix="/v1", tags=["watch"],
                   dependencies=[Depends(require_token)])


def _sse(path: str, from_start: bool):
    async def gen():
        async for obj in tail_transcript(path, from_start=from_start):
            yield f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream")


@router.get("/sessions/{session_id}/watch")
async def watch_session(session_id: str, from_start: bool = Query(False)):
    c = MANAGER.get(session_id)
    if not c or not c.transcript_path:
        raise HTTPException(404, "sessão (ou transcript) não encontrada")
    return _sse(c.transcript_path, from_start)


@router.get("/discovered/{session_id}/watch")
async def watch_discovered(session_id: str, from_start: bool = Query(False)):
    d = resume_mod.find(session_id)
    if not d:
        raise HTTPException(404, "sessão não encontrada")
    slug = (d.cwd or "").replace("/", "-").replace(".", "-")
    import os
    path = os.path.expanduser(f"~/.claude/projects/{slug}/{session_id}.jsonl")
    return _sse(path, from_start)
