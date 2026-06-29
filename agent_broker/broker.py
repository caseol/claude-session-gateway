"""Broker A2A — registry de agentes (keyed por session_id) + inboxes + roteamento
de mensagens entre sessões Claude Code. Entrega asks síncronos via o Session
Gateway (resume-fork). Porta 3470. Auth bearer (BROKER_TOKEN em state/.env).

Registro por session_id permite vários agentes na mesma lane (ex.: múltiplos
'original'). Alvos podem ser endereçados por session_id, display_name ou lane.
"""
from __future__ import annotations

import asyncio
import json
import os
import secrets
import sys
import time
import uuid
from pathlib import Path
from typing import Optional

import httpx
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

sys.path.insert(0, os.path.dirname(__file__))
import common  # noqa: E402

TOKEN = common.get_or_create_token()


# ----------------- registry (keyed por session_id) -----------------

class Registry:
    def __init__(self) -> None:
        self.agents: dict[str, dict] = {}   # session_id -> info
        self._load()

    def _load(self) -> None:
        try:
            data = json.loads(common.REGISTRY.read_text())
            # tolera registro antigo (keyed por lane) — descarta
            self.agents = {k: v for k, v in data.items()
                           if isinstance(v, dict) and v.get("session_id") == k}
        except Exception:  # noqa: BLE001
            self.agents = {}

    def _save(self) -> None:
        tmp = common.REGISTRY.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.agents, ensure_ascii=False, indent=1))
        os.replace(tmp, common.REGISTRY)

    def register(self, lane: str, session_id: str, display_name: str, pid: int) -> None:
        now = time.time()
        prev = self.agents.get(session_id, {})
        self.agents[session_id] = {
            "lane": lane, "session_id": session_id,
            "display_name": display_name or lane, "pid": pid,
            "registered_at": prev.get("registered_at", now), "last_seen": now,
            "status": "online",
        }
        self._save()

    def deregister(self, session_id: str) -> None:
        if session_id in self.agents:
            del self.agents[session_id]
            self._save()

    def heartbeat(self, session_id: str) -> bool:
        a = self.agents.get(session_id)
        if not a:
            return False
        a["last_seen"] = time.time()
        return True

    def online(self) -> list[dict]:
        cutoff = time.time() - common.HEARTBEAT_TTL
        return [a for a in self.agents.values() if a["last_seen"] >= cutoff]

    def resolve(self, target: str, caller_sid: str = "") -> Optional[dict]:
        """Resolve um alvo (session_id exato > display_name > lane) para um agente
        online. Em empate de lane/nome, o mais recente que não seja o caller."""
        online = self.online()
        # 1) session_id exato
        for a in online:
            if a["session_id"] == target:
                return a
        # 2) display_name  3) lane — escolhe o mais recente != caller
        for key in ("display_name", "lane"):
            cands = [a for a in online
                     if a.get(key) == target and a["session_id"] != caller_sid]
            if cands:
                return max(cands, key=lambda a: a["last_seen"])
        return None

    def sweep(self) -> None:
        cutoff = time.time() - common.HEARTBEAT_TTL
        stale = [s for s, a in self.agents.items() if a["last_seen"] < cutoff]
        for s in stale:
            del self.agents[s]
        if stale:
            self._save()


REG = Registry()


# ----------------- inboxes (por session_id) -----------------

def inbox_path(sid: str) -> Path:
    safe = sid.replace("/", "_")
    return common.INBOX_DIR / f"{safe}.jsonl"


def inbox_append(sid: str, msg: dict) -> None:
    common.ensure_dirs()
    with open(inbox_path(sid), "a") as f:
        f.write(json.dumps(msg, ensure_ascii=False) + "\n")


def inbox_load(sid: str) -> list[dict]:
    p = inbox_path(sid)
    if not p.exists():
        return []
    msgs: dict[str, dict] = {}
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except json.JSONDecodeError:
            continue
        if o.get("_ack"):
            if o["_ack"] in msgs:
                msgs[o["_ack"]]["read"] = True
        else:
            msgs[o["id"]] = o
    return list(msgs.values())


def inbox_mark_read(sid: str, ids: list[str]) -> None:
    with open(inbox_path(sid), "a") as f:
        for i in ids:
            f.write(json.dumps({"_ack": i}) + "\n")


# ----------------- controle do ask síncrono -----------------

class AskControl:
    def __init__(self) -> None:
        self.inflight = 0
        self.locks: dict[str, bool] = {}      # keyed por session_id alvo

    def busy(self, sid: str) -> bool:
        return self.locks.get(sid, False)


ASK = AskControl()


# ----------------- app -----------------

app = FastAPI(title="Agent Broker", version="0.2.0")


async def require_token(authorization: str = Header(default="")) -> None:
    if not secrets.compare_digest(authorization, f"Bearer {TOKEN}"):
        raise HTTPException(401, "invalid broker token")


# ----- schemas -----
class RegisterReq(BaseModel):
    lane: str
    session_id: str
    display_name: Optional[str] = None
    pid: Optional[int] = 0


class SessionReq(BaseModel):
    session_id: str


class AskReq(BaseModel):
    target: str
    message: str
    timeout_s: int = common.ASK_TIMEOUT_DEFAULT


class SendReq(BaseModel):
    target: str
    message: str


class BroadcastReq(BaseModel):
    message: str


# ----- lifecycle -----
@app.post("/register")
async def register(req: RegisterReq):
    REG.register(req.lane, req.session_id, req.display_name or req.lane, req.pid or 0)
    return {"ok": True, "lane": req.lane, "session_id": req.session_id}


@app.post("/deregister")
async def deregister(req: SessionReq):
    REG.deregister(req.session_id)
    return {"ok": True}


@app.post("/heartbeat")
async def heartbeat(req: SessionReq):
    return {"ok": REG.heartbeat(req.session_id)}


@app.get("/agents")
async def agents(authorization: str = Header(default="")):
    await require_token(authorization)
    return REG.online()


# ----- async messaging -----
@app.post("/send")
async def send(req: SendReq, authorization: str = Header(default=""),
               x_agent_lane: str = Header(default=""),
               x_agent_session: str = Header(default="")):
    await require_token(authorization)
    tgt = REG.resolve(req.target, x_agent_session)
    if not tgt:
        return {"ok": False, "error": "offline", "detail": f"alvo '{req.target}' não encontrado"}
    msg = {"id": uuid.uuid4().hex[:12], "ts": time.time(),
           "from_lane": x_agent_lane, "from_session": x_agent_session,
           "body": req.message, "read": False}
    inbox_append(tgt["session_id"], msg)
    return {"ok": True, "delivered_to": tgt["lane"],
            "session_id": tgt["session_id"], "id": msg["id"]}


@app.post("/broadcast")
async def broadcast(req: BroadcastReq, authorization: str = Header(default=""),
                    x_agent_lane: str = Header(default=""),
                    x_agent_session: str = Header(default="")):
    await require_token(authorization)
    targets = [a for a in REG.online() if a["session_id"] != x_agent_session]
    for t in targets:
        inbox_append(t["session_id"],
                     {"id": uuid.uuid4().hex[:12], "ts": time.time(),
                      "from_lane": x_agent_lane, "from_session": x_agent_session,
                      "body": req.message, "read": False})
    return {"ok": True, "delivered_to": [t["lane"] for t in targets]}


@app.get("/inbox/{sid}")
async def get_inbox(sid: str, authorization: str = Header(default="")):
    await require_token(authorization)
    msgs = [m for m in inbox_load(sid) if not m.get("read")]
    return {"session_id": sid, "unread": msgs}


@app.post("/inbox/{sid}/read")
async def read_inbox(sid: str, authorization: str = Header(default=""), max: int = 50):
    await require_token(authorization)
    msgs = [m for m in inbox_load(sid) if not m.get("read")][:max]
    inbox_mark_read(sid, [m["id"] for m in msgs])
    return {"session_id": sid, "messages": msgs}


# ----- sync ask (via Session Gateway resume-fork) -----
@app.post("/ask")
async def ask(req: AskReq, authorization: str = Header(default=""),
              x_agent_lane: str = Header(default=""),
              x_agent_session: str = Header(default="")):
    await require_token(authorization)

    tgt = REG.resolve(req.target, x_agent_session)
    if not tgt:
        return {"ok": False, "error": "offline",
                "detail": f"alvo '{req.target}' não está online"}
    tsid, tlane = tgt["session_id"], tgt["lane"]
    if tsid == x_agent_session:
        raise HTTPException(422, "não pode perguntar a si mesmo")
    if ASK.inflight >= common.MAX_ASK_DEPTH:
        return {"ok": False, "error": "depth_exceeded",
                "detail": f"asks em voo >= {common.MAX_ASK_DEPTH}"}
    if ASK.busy(tsid):
        return {"ok": False, "error": "busy",
                "detail": f"alvo {tlane} já está respondendo um ask"}

    gw_token = common.gateway_token()
    if not gw_token:
        raise HTTPException(503, "Session Gateway token indisponível")

    timeout_s = min(max(req.timeout_s, 5), common.ASK_TIMEOUT_CAP)
    framed = (f"[mensagem do agente '{x_agent_lane or 'desconhecido'}' via A2A — "
              f"responda diretamente; sua resposta volta para o remetente]\n\n{req.message}")

    ASK.inflight += 1
    ASK.locks[tsid] = True
    t0 = time.time()
    try:
        async with httpx.AsyncClient(timeout=timeout_s + 15) as client:
            r = await client.post(
                f"{common.GW_URL}/v1/discovered/{tsid}/prompt",
                headers={"Authorization": f"Bearer {gw_token}"},
                json={"prompt": framed, "mode": "fork",
                      "lane": tlane, "permission_mode": common.ASK_PERMISSION_MODE})
        if r.status_code != 200:
            return {"ok": False, "error": "gateway_error",
                    "status": r.status_code, "detail": r.text[:300]}
        data = r.json()
        reply = data.get("result") or data.get("text") or ""
        return {"ok": True, "reply": reply, "from": tlane,
                "from_session": tsid, "elapsed_s": round(time.time() - t0, 2)}
    except (httpx.TimeoutException, asyncio.TimeoutError):
        return {"ok": False, "error": "timeout", "from": tlane}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": "exception", "detail": str(e)}
    finally:
        ASK.inflight -= 1
        ASK.locks[tsid] = False


@app.get("/healthz")
async def healthz():
    return {"ok": True, "online": len(REG.online()), "inflight_asks": ASK.inflight}


@app.on_event("startup")
async def _sweeper():
    async def loop():
        while True:
            await asyncio.sleep(common.SWEEP_INTERVAL)
            REG.sweep()
    asyncio.create_task(loop())


@app.exception_handler(Exception)
async def _unhandled(request, exc):  # noqa: ANN001
    return JSONResponse(status_code=500,
                        content={"error": {"type": type(exc).__name__,
                                           "message": str(exc)}})


def main() -> None:
    import uvicorn
    common.ensure_dirs()
    print(f"Agent Broker em http://{common.HOST}:{common.PORT} (token {TOKEN[:8]}...)")
    uvicorn.run(app, host=common.HOST, port=common.PORT, log_level="warning")


if __name__ == "__main__":
    main()
