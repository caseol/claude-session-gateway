"""Encode/decode defensivo do protocolo stream-json do Claude Code v2.1.x.

Baseado em calibração empírica (ver tests/fixtures/NOTES.md). Tolerante a drift:
nunca quebra em tipo desconhecido; reassembla linhas fragmentadas por buffer de bytes.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterator, Optional


# ---------- ENCODE (gateway -> stdin do claude) ----------

def encode_user_turn(prompt: str) -> bytes:
    obj = {"type": "user", "message": {"role": "user", "content": prompt}}
    return (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")


def encode_set_permission_mode(mode: str) -> tuple[str, bytes]:
    """Retorna (request_id, bytes) para mudar o modo de permissão no turno."""
    rid = "req_" + uuid.uuid4().hex[:12]
    obj = {
        "type": "control_request",
        "request_id": rid,
        "request": {"subtype": "set_permission_mode", "mode": mode},
    }
    return rid, (json.dumps(obj) + "\n").encode("utf-8")


# ---------- DECODE (stdout do claude -> eventos normalizados) ----------

class LineBuffer:
    """Acumula bytes e emite linhas completas (split em \\n), tolerando leituras
    que não se alinham a fronteiras de linha."""

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, chunk: bytes) -> Iterator[str]:
        self._buf.extend(chunk)
        while True:
            nl = self._buf.find(b"\n")
            if nl < 0:
                break
            line = self._buf[:nl]
            del self._buf[: nl + 1]
            s = line.decode("utf-8", "replace").strip()
            if s:
                yield s

    def flush(self) -> Iterator[str]:
        s = bytes(self._buf).decode("utf-8", "replace").strip()
        self._buf.clear()
        if s:
            yield s


@dataclass
class NormEvent:
    """Evento normalizado emitido ao consumidor (HTTP/SSE)."""
    kind: str                      # init|status|text_delta|thinking_delta|message|user|result|control_response|raw|parse_error
    text: str = ""                 # texto incremental ou final, quando aplicável
    session_id: Optional[str] = None
    raw: Any = field(default=None)  # objeto original (para clientes que querem tudo)
    is_terminal: bool = False       # True no result (fim do turno)
    is_error: bool = False
    meta: dict = field(default_factory=dict)


def parse_line(line: str) -> NormEvent:
    """Converte uma linha JSON do stdout num NormEvent. Nunca levanta."""
    if not line.startswith("{"):
        # preâmbulo/banner do launcher -> ignora como raw silencioso
        return NormEvent(kind="raw", raw=line, meta={"preamble": True})
    try:
        o = json.loads(line)
    except json.JSONDecodeError:
        return NormEvent(kind="parse_error", raw=line)

    t = o.get("type")
    sid = o.get("session_id")

    if t == "system":
        st = o.get("subtype")
        if st == "init":
            return NormEvent(kind="init", session_id=o.get("session_id"), raw=o,
                             meta={"model": o.get("model"),
                                   "permissionMode": o.get("permissionMode"),
                                   "cwd": o.get("cwd")})
        return NormEvent(kind="status", session_id=sid, raw=o,
                         meta={"status": o.get("status")})

    if t == "stream_event":
        ev = o.get("event", {}) or {}
        et = ev.get("type")
        if et == "content_block_delta":
            delta = ev.get("delta", {}) or {}
            dt = delta.get("type")
            if dt == "text_delta":
                return NormEvent(kind="text_delta", text=delta.get("text", ""),
                                 session_id=sid, raw=o)
            if dt == "thinking_delta":
                return NormEvent(kind="thinking_delta", text=delta.get("thinking", ""),
                                 session_id=sid, raw=o)
        return NormEvent(kind="raw", session_id=sid, raw=o)

    if t == "assistant":
        msg = o.get("message", {}) or {}
        txt = "".join(b.get("text", "") for b in (msg.get("content") or [])
                      if isinstance(b, dict) and b.get("type") == "text")
        return NormEvent(kind="message", text=txt, session_id=sid, raw=o,
                         meta={"stop_reason": msg.get("stop_reason")})

    if t == "user":
        return NormEvent(kind="user", session_id=sid, raw=o,
                         meta={"isReplay": o.get("isReplay"),
                               "isSynthetic": o.get("isSynthetic")})

    if t == "result":
        return NormEvent(kind="result", text=o.get("result", "") or "",
                         session_id=sid, raw=o, is_terminal=True,
                         is_error=bool(o.get("is_error")),
                         meta={"stop_reason": o.get("stop_reason"),
                               "usage": o.get("usage"),
                               "total_cost_usd": o.get("total_cost_usd"),
                               "subtype": o.get("subtype"),
                               "api_error_status": o.get("api_error_status")})

    if t == "control_response":
        resp = o.get("response", {}) or {}
        return NormEvent(kind="control_response", session_id=sid, raw=o,
                         meta={"request_id": resp.get("request_id"),
                               "subtype": resp.get("subtype")})

    return NormEvent(kind="raw", session_id=sid, raw=o)
