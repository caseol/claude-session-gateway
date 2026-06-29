#!/usr/bin/env python3
"""a2a_shim — servidor MCP (stdio, JSON-RPC artesanal) que o Claude Code carrega
(via ~/.claude/.mcp.json global ou --mcp-config). Expõe 6 ferramentas A2A; cada
chamada é encaminhada ao Broker HTTP (porta 3470).

Identidade AUTO-DESCOBERTA (env explícito tem precedência):
- lane: AGENT_LANE | porta do ANTHROPIC_BASE_URL (3457=go,3458=nv,3459=zen) | original
- session_id: AGENT_SESSION_ID | sessionId de ~/.claude/sessions/<ppid>.json
- broker token: BROKER_TOKEN | ~/.local/share/agent-broker/state/.env
A2A_NO_SHIM=1 deixa o shim inerte (não registra) — usado em forks/sessões hospedadas.

Sem dependências externas: só stdlib (urllib). Logs apenas em stderr.
"""
from __future__ import annotations

import atexit
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request

# Resolvidos no startup por resolve_identity()
LANE = "unknown"
SESSION = ""
BROKER_PORT = os.environ.get("BROKER_PORT", "3470")
BROKER_TOKEN = ""
BROKER = f"http://127.0.0.1:{BROKER_PORT}"
NO_SHIM = os.environ.get("A2A_NO_SHIM", "0") == "1"

SERVER_INFO = {"name": "a2a", "version": "0.2.0"}

_LANE_BY_PORT = {"3457": "go", "3458": "nv", "3459": "zen"}


def log(*a):
    print("[a2a_shim]", *a, file=sys.stderr, flush=True)


# ---------- auto-identidade ----------

def _lane_from_base_url() -> str:
    url = os.environ.get("ANTHROPIC_BASE_URL", "")
    for port, lane in _LANE_BY_PORT.items():
        if f":{port}" in url:
            return lane
    return "original"


def _session_from_proc(retry_s: float = 5.0) -> str:
    """sessionId da sessão claude pai, lido de ~/.claude/sessions/<ppid>.json (o
    nome do arquivo = pid do claude = pai direto do shim). Retry curto para o caso
    do arquivo ainda não existir no initialize. Retorna "" se não achar (ex.: sessão
    efêmera/--no-session-persistence) — nesse caso o shim não registra."""
    sdir = os.path.expanduser("~/.claude/sessions")
    ppid = os.getppid()
    deadline = time.time() + retry_s
    while time.time() < deadline:
        f = os.path.join(sdir, f"{ppid}.json")
        if os.path.exists(f):
            try:
                return json.load(open(f)).get("sessionId", "")
            except Exception:  # noqa: BLE001
                pass
        time.sleep(0.4)
    return ""


def _token_from_env_file() -> str:
    f = os.path.expanduser("~/.local/share/agent-broker/state/.env")
    try:
        for line in open(f):
            if line.startswith("BROKER_TOKEN="):
                return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return ""


def resolve_identity() -> None:
    global LANE, SESSION, BROKER_TOKEN
    LANE = os.environ.get("AGENT_LANE") or _lane_from_base_url()
    SESSION = os.environ.get("AGENT_SESSION_ID") or _session_from_proc()
    BROKER_TOKEN = os.environ.get("BROKER_TOKEN") or _token_from_env_file()
    log(f"identidade: lane={LANE} session={SESSION[:8]} no_shim={NO_SHIM}")


# ---------- HTTP para o broker ----------

def _call_broker(method: str, path: str, body: dict | None = None) -> dict:
    url = BROKER + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {BROKER_TOKEN}")
    req.add_header("Content-Type", "application/json")
    req.add_header("X-Agent-Lane", LANE)
    req.add_header("X-Agent-Session", SESSION)
    try:
        with urllib.request.urlopen(req, timeout=330) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"_error": f"HTTP {e.code}", "detail": e.read().decode()[:300]}
    except Exception as e:  # noqa: BLE001
        return {"_error": "broker_unreachable", "detail": str(e)}


# ---------- ferramentas ----------

TOOLS = [
    {"name": "list_agents",
     "description": "Lista os agentes (sessões Claude Code) online: original, go, zen, nv.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "ask_agent",
     "description": "Pergunta SÍNCRONA a outro agente e espera a resposta. O agente alvo "
                    "responde com seu próprio contexto. Use para consultar um colega.",
     "inputSchema": {"type": "object",
                     "properties": {"target": {"type": "string",
                                               "description": "lane alvo: original|go|zen|nv"},
                                    "message": {"type": "string"},
                                    "timeout_s": {"type": "integer", "default": 60}},
                     "required": ["target", "message"]}},
    {"name": "send_message",
     "description": "Envia mensagem ASSÍNCRONA para a inbox de outro agente (não espera resposta).",
     "inputSchema": {"type": "object",
                     "properties": {"target": {"type": "string"},
                                    "message": {"type": "string"}},
                     "required": ["target", "message"]}},
    {"name": "check_inbox",
     "description": "Mostra as mensagens não lidas na sua inbox (sem marcá-las como lidas).",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "read_messages",
     "description": "Lê e marca como lidas as mensagens da sua inbox.",
     "inputSchema": {"type": "object",
                     "properties": {"max": {"type": "integer", "default": 50}}}},
    {"name": "broadcast",
     "description": "Envia uma mensagem assíncrona para TODOS os outros agentes online.",
     "inputSchema": {"type": "object",
                     "properties": {"message": {"type": "string"}},
                     "required": ["message"]}},
]


def dispatch_tool(name: str, args: dict) -> dict:
    if name == "list_agents":
        return _call_broker("GET", "/agents")
    if name == "ask_agent":
        return _call_broker("POST", "/ask",
                            {"target": args["target"], "message": args["message"],
                             "timeout_s": int(args.get("timeout_s", 60))})
    if name == "send_message":
        return _call_broker("POST", "/send",
                            {"target": args["target"], "message": args["message"]})
    if name == "check_inbox":
        return _call_broker("GET", f"/inbox/{SESSION}")
    if name == "read_messages":
        return _call_broker("POST", f"/inbox/{SESSION}/read?max={int(args.get('max', 50))}")
    if name == "broadcast":
        return _call_broker("POST", "/broadcast", {"message": args["message"]})
    return {"_error": "unknown_tool", "name": name}


# ---------- registro / heartbeat / desregistro ----------

_registered = False


def register() -> None:
    global _registered
    if NO_SHIM or not SESSION:
        log("inerte (A2A_NO_SHIM ou sem session_id) — não registra")
        return
    out = _call_broker("POST", "/register",
                       {"lane": LANE, "session_id": SESSION,
                        "display_name": os.environ.get("AGENT_DISPLAY_NAME", LANE),
                        "pid": os.getppid()})
    _registered = not out.get("_error")
    log("registrado:" if _registered else "falha ao registrar:", out)


def deregister() -> None:
    if _registered:
        _call_broker("POST", "/deregister", {"session_id": SESSION})
        log("desregistrado")


def _heartbeat_loop() -> None:
    # Send full identity so the broker can re-register us if it restarted (upsert).
    while True:
        time.sleep(60)
        _call_broker("POST", "/heartbeat",
                     {"session_id": SESSION, "lane": LANE,
                      "display_name": os.environ.get("AGENT_DISPLAY_NAME", LANE),
                      "pid": os.getppid()})


# ---------- JSON-RPC ----------

def reply(mid, result=None, error=None):
    msg = {"jsonrpc": "2.0", "id": mid}
    if error is not None:
        msg["error"] = error
    else:
        msg["result"] = result
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def handle(msg: dict) -> None:
    method = msg.get("method")
    mid = msg.get("id")

    if method == "initialize":
        params = msg.get("params", {}) or {}
        proto = params.get("protocolVersion", "2025-06-18")
        resolve_identity()
        register()
        if not NO_SHIM and _registered:
            threading.Thread(target=_heartbeat_loop, daemon=True).start()
        reply(mid, {"protocolVersion": proto,
                    "capabilities": {"tools": {}},
                    "serverInfo": SERVER_INFO})
    elif method == "notifications/initialized":
        pass  # notificação, sem resposta
    elif method == "ping":
        reply(mid, {})
    elif method == "tools/list":
        reply(mid, {"tools": TOOLS})
    elif method == "tools/call":
        params = msg.get("params", {}) or {}
        name = params.get("name", "")
        args = params.get("arguments", {}) or {}
        try:
            out = dispatch_tool(name, args)
        except KeyError as e:
            out = {"_error": "missing_argument", "detail": str(e)}
        text = json.dumps(out, ensure_ascii=False)
        is_err = isinstance(out, dict) and bool(out.get("_error") or out.get("ok") is False)
        reply(mid, {"content": [{"type": "text", "text": text}], "isError": is_err})
    elif mid is not None:
        reply(mid, error={"code": -32601, "message": f"method not found: {method}"})


def main() -> None:
    log(f"iniciado (aguardando initialize) broker={BROKER}")
    atexit.register(deregister)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        try:
            handle(msg)
        except Exception as e:  # noqa: BLE001
            log("erro:", repr(e))


if __name__ == "__main__":
    main()
