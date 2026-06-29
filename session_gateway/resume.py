"""Mecanismo SECUNDÁRIO: descobrir sessões de terminal já abertas e injetar um
turno único via --resume/--fork-session. Não-destrutivo por padrão (fork)."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import time
from pathlib import Path

from . import config
from .models import DiscoveredSession

SESSIONS_DIR = Path(os.path.expanduser("~/.claude/sessions"))


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def discover() -> list[DiscoveredSession]:
    out: list[DiscoveredSession] = []
    if not SESSIONS_DIR.exists():
        return out
    for f in SESSIONS_DIR.glob("*.json"):
        try:
            d = json.loads(f.read_text())
        except Exception:  # noqa: BLE001
            continue
        pid = d.get("pid", 0)
        alive = _pid_alive(pid)
        status = d.get("status")
        safe = bool(alive and status == "idle")
        out.append(DiscoveredSession(
            session_id=d.get("sessionId", ""), pid=pid, cwd=d.get("cwd", ""),
            status=status, kind=d.get("kind"), version=d.get("version"),
            safe_to_drive=safe))
    return out


def find(session_id: str) -> DiscoveredSession | None:
    for s in discover():
        if s.session_id == session_id:
            return s
    return None


def _resume_argv0(lane: str | None) -> str:
    """Para resumir a sessão de uma lane usamos o MESMO comando dela (wrapper que
    seta o backend correto), conforme configurado em lanes.json. Sem lane → `claude`."""
    from . import lanes
    cmd = lanes.command_for(lane) if lane else "claude"
    if os.path.isabs(cmd) and os.path.exists(cmd):
        return cmd
    found = shutil.which(cmd)
    if found:
        return found
    cand = os.path.expanduser(f"~/.local/bin/{cmd}")
    return cand if os.path.exists(cand) else "claude"


def _extract_json(stdout: bytes) -> dict:
    """Tolera o banner do launcher antes do JSON do --output-format json."""
    text = stdout.decode("utf-8", "replace")
    idx = text.find("{")
    if idx >= 0:
        try:
            return json.loads(text[idx:])
        except json.JSONDecodeError:
            pass
    return {"raw": text, "_note": "saída não-JSON", "_ts": time.time()}


async def one_shot(session_id: str, prompt: str, mode: str = "fork",
                   permission_mode: str | None = None,
                   lane: str | None = None,
                   timeout_s: int | None = None) -> dict:
    """Roda `claude[-lane] -p --resume <sid> [--fork-session]` e devolve o JSON do result."""
    disc = find(session_id)
    if disc is None:
        raise KeyError(f"sessão {session_id} não encontrada em ~/.claude/sessions")
    if mode == "resume" and not disc.safe_to_drive:
        raise RuntimeError(
            f"sessão {session_id} não está segura para dirigir "
            f"(status={disc.status}); use mode=fork")

    pm = permission_mode or config.DEFAULT_PERMISSION_MODE
    if pm not in config.VALID_PERMISSION_MODES:
        raise ValueError(f"permission_mode inválido: {pm}")
    if pm in config.DANGEROUS_MODES and not config.ALLOW_DANGEROUS_MODES:
        raise PermissionError(f"modo '{pm}' bloqueado")

    argv = [_resume_argv0(lane), "-p",
            "--resume", session_id, "--output-format", "json",
            "--permission-mode", pm]
    if mode == "fork":
        argv += ["--fork-session"]

    env = dict(os.environ, A2A_NO_SHIM="1")  # turno transitório: sem shim/registro A2A
    proc = await asyncio.create_subprocess_exec(
        *argv, cwd=disc.cwd or os.path.expanduser("~"), env=env,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE)
    out, err = await asyncio.wait_for(
        proc.communicate(input=prompt.encode("utf-8")),
        timeout=timeout_s or config.TURN_TIMEOUT_SECONDS)
    if proc.returncode != 0:
        raise RuntimeError(f"claude saiu com {proc.returncode}: "
                           f"{err.decode('utf-8','replace')[:500]}")
    return _extract_json(out)
