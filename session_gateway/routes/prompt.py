"""Envio de prompt a uma sessão persistente (sync ou SSE)."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from .. import config
from ..auth import require_token
from ..models import PromptReq, PromptResp
from ..session_manager import MANAGER, _validate_mode

router = APIRouter(prefix="/v1/sessions", tags=["prompt"],
                   dependencies=[Depends(require_token)])


def _check_mode(mode: str | None) -> str | None:
    if mode is None:
        return None
    try:
        _validate_mode(mode)
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except ValueError as e:
        raise HTTPException(422, str(e))
    return mode


@router.post("/{session_id}/prompt")
async def prompt(session_id: str, req: PromptReq):
    child = MANAGER.get(session_id)
    if not child:
        raise HTTPException(404, "sessão não encontrada")
    mode = _check_mode(req.permission_mode)

    if req.stream:
        async def gen():
            try:
                async for ev in child.run_turn(req.prompt, mode):
                    payload = {"kind": ev.kind, "text": ev.text,
                               "session_id": ev.session_id, "meta": ev.meta}
                    yield f"event: {ev.kind}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
            except Exception as e:  # noqa: BLE001
                err = {"kind": "error", "message": str(e)}
                yield f"event: error\ndata: {json.dumps(err)}\n\n"
        return StreamingResponse(gen(), media_type="text/event-stream")

    # sync: acumula e devolve no result
    buf: list[str] = []
    final = ""
    stop_reason = None
    is_error = False
    usage = None
    cost = None
    async for ev in child.run_turn(req.prompt, mode):
        if ev.kind == "text_delta":
            buf.append(ev.text)
        elif ev.kind == "result":
            final = ev.text or "".join(buf)
            stop_reason = ev.meta.get("stop_reason")
            is_error = ev.is_error
            usage = ev.meta.get("usage")
            cost = ev.meta.get("total_cost_usd")
    if is_error and not final:
        raise HTTPException(502, f"turno falhou: {stop_reason}")
    return PromptResp(session_id=child.session_id, text=final or "".join(buf),
                      stop_reason=stop_reason, is_error=is_error,
                      usage=usage, cost_usd=cost)
