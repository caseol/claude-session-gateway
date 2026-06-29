"""PersistentClaudeChild — um processo `claude` headless por sessão/lane, dirigido
via stream-json. Serializa turnos (1 por vez), suporta modo de permissão por turno
(control_request) e restart-on-crash preservando o session_id (--resume)."""
from __future__ import annotations

import asyncio
import collections
import os
import time
from pathlib import Path
from typing import AsyncIterator, Optional

from . import config, sdk_protocol as proto
from .lanes import Lane, resolve_command

_TERMINAL_SENTINEL = object()


class PersistentClaudeChild:
    def __init__(self, lane: Lane, session_id: str, cwd: str,
                 model: Optional[str] = None,
                 create_permission_mode: str = "plan",
                 mcp_config: Optional[list[str]] = None):
        self.lane = lane
        self.session_id = session_id
        self.cwd = cwd
        self.model = model
        self.permission_mode = create_permission_mode
        self.mcp_config = mcp_config or []

        self.status = "starting"          # starting|idle|busy|crashed|stopped
        self.started_at = time.time()
        self.last_turn_at: Optional[float] = None
        self.transcript_path: Optional[str] = None

        self._proc: Optional[asyncio.subprocess.Process] = None
        self._turn_lock = asyncio.Lock()
        self._turn_q: Optional[asyncio.Queue] = None
        self._init_evt = asyncio.Event()
        self._ctrl_waiters: dict[str, asyncio.Future] = {}
        self._stderr_ring: collections.deque[str] = collections.deque(maxlen=50)
        self._pump_task: Optional[asyncio.Task] = None
        self._stderr_task: Optional[asyncio.Task] = None

    # ---------- spawn ----------

    def _build_argv(self, resume: bool) -> list[str]:
        argv = [resolve_command(self.lane), "-p", "--verbose",
                "--input-format", "stream-json",
                "--output-format", "stream-json",
                "--include-partial-messages", "--replay-user-messages",
                "--permission-mode", self.permission_mode]
        if resume:
            argv += ["--resume", self.session_id]
        else:
            argv += ["--session-id", self.session_id]
        if self.model:
            argv += ["--model", self.model]
        for c in self.mcp_config:
            argv += ["--mcp-config", c]
        return argv

    async def start(self, resume: bool = False) -> None:
        argv = self._build_argv(resume)
        # Sessões hospedadas pelo gateway não viram agentes A2A por padrão
        # (evita colisão de lane com sessões interativas). Para integrá-las ao
        # A2A, passe mcp_config explícito do shim ao criar a sessão.
        env = dict(os.environ, A2A_NO_SHIM="1")
        self._proc = await asyncio.create_subprocess_exec(
            *argv, cwd=self.cwd, env=env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._audit("spawn", argv=" ".join(argv), resume=resume)
        self._pump_task = asyncio.create_task(self._stdout_pump())
        self._stderr_task = asyncio.create_task(self._stderr_pump())
        # IMPORTANTE: o claude só emite system/init APÓS a 1a linha de stdin, então
        # NÃO esperamos por ele aqui (seria deadlock). O session_id já é conhecido
        # (passado via --session-id); o init refina o transcript_path no 1o turno.
        if not self.transcript_path:
            self._set_transcript_from_cwd()
        await asyncio.sleep(0.8)  # detecta crash precoce (args inválidos etc.)
        if self._proc.returncode is not None:
            await self.stop()
            raise RuntimeError(
                f"lane {self.lane.name}: claude saiu cedo (rc={self._proc.returncode}). "
                "stderr: " + " | ".join(self._stderr_ring))
        self.status = "idle"

    def _set_transcript_from_cwd(self) -> None:
        slug = self.cwd.replace("/", "-").replace(".", "-")
        self.transcript_path = os.path.expanduser(
            f"~/.claude/projects/{slug}/{self.session_id}.jsonl")

    # ---------- pumps ----------

    async def _stdout_pump(self) -> None:
        assert self._proc and self._proc.stdout
        lb = proto.LineBuffer()
        try:
            while True:
                chunk = await self._proc.stdout.read(65536)
                if not chunk:
                    break
                for line in lb.feed(chunk):
                    self._dispatch(proto.parse_line(line))
            for line in lb.flush():
                self._dispatch(proto.parse_line(line))
        except Exception as e:  # noqa: BLE001
            self._stderr_ring.append(f"[pump error] {e!r}")
        finally:
            # EOF: processo morreu
            if self.status != "stopped":
                self.status = "crashed"
            if self._turn_q is not None:
                ev = proto.NormEvent(kind="result", is_terminal=True, is_error=True,
                                     session_id=self.session_id,
                                     meta={"stop_reason": "process_exit",
                                           "stderr": list(self._stderr_ring)})
                self._turn_q.put_nowait(ev)
                self._turn_q.put_nowait(_TERMINAL_SENTINEL)

    async def _stderr_pump(self) -> None:
        assert self._proc and self._proc.stderr
        try:
            while True:
                line = await self._proc.stderr.readline()
                if not line:
                    break
                s = line.decode("utf-8", "replace").rstrip()
                if s:
                    self._stderr_ring.append(s)
        except Exception:  # noqa: BLE001
            pass

    def _dispatch(self, ev: proto.NormEvent) -> None:
        if ev.kind == "init":
            if ev.session_id:
                self.session_id = ev.session_id
            self._derive_transcript_path(ev)
            self._init_evt.set()
            return
        if ev.kind == "control_response":
            rid = ev.meta.get("request_id")
            fut = self._ctrl_waiters.pop(rid, None)
            if fut and not fut.done():
                fut.set_result(ev)
            return
        if self._turn_q is not None:
            self._turn_q.put_nowait(ev)
            if ev.is_terminal:
                self._turn_q.put_nowait(_TERMINAL_SENTINEL)

    def _derive_transcript_path(self, ev: proto.NormEvent) -> None:
        # Caminho robusto: derivado de memory_paths.auto do init (não chuta o slug).
        raw = ev.raw or {}
        mp = (raw.get("memory_paths") or {}).get("auto")
        if mp:
            project_dir = Path(mp).parent
            self.transcript_path = str(project_dir / f"{self.session_id}.jsonl")
        else:
            slug = ev.meta.get("cwd", self.cwd).replace("/", "-").replace(".", "-")
            self.transcript_path = os.path.expanduser(
                f"~/.claude/projects/{slug}/{self.session_id}.jsonl")

    # ---------- turno ----------

    async def run_turn(self, prompt: str, permission_mode: Optional[str] = None
                       ) -> AsyncIterator[proto.NormEvent]:
        """Executa um turno e emite NormEvents até o terminador. Serializado."""
        async with self._turn_lock:
            if self.status == "crashed":
                await self._respawn()
            self._turn_q = asyncio.Queue()
            self.status = "busy"
            self.last_turn_at = time.time()
            try:
                if permission_mode and permission_mode != self.permission_mode:
                    await self._set_permission_mode(permission_mode)
                assert self._proc and self._proc.stdin
                self._proc.stdin.write(proto.encode_user_turn(prompt))
                await self._proc.stdin.drain()
                while True:
                    item = await self._turn_q.get()
                    if item is _TERMINAL_SENTINEL:
                        break
                    yield item
            finally:
                self._turn_q = None
                if self.status == "busy":
                    self.status = "idle"

    async def _set_permission_mode(self, mode: str) -> None:
        rid, payload = proto.encode_set_permission_mode(mode)
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._ctrl_waiters[rid] = fut
        assert self._proc and self._proc.stdin
        self._proc.stdin.write(payload)
        await self._proc.stdin.drain()
        try:
            await asyncio.wait_for(fut, timeout=10)
            self.permission_mode = mode
        except asyncio.TimeoutError:
            self._ctrl_waiters.pop(rid, None)
            # segue assim mesmo; o modo de criação continua valendo

    async def _respawn(self) -> None:
        self._stderr_ring.clear()
        self._init_evt = asyncio.Event()
        await self.start(resume=True)

    # ---------- ciclo de vida ----------

    async def stop(self) -> None:
        self.status = "stopped"
        if self._proc and self._proc.returncode is None:
            try:
                if self._proc.stdin:
                    self._proc.stdin.close()
            except Exception:  # noqa: BLE001
                pass
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._proc.terminate()
                try:
                    await asyncio.wait_for(self._proc.wait(), timeout=3)
                except asyncio.TimeoutError:
                    self._proc.kill()
        for t in (self._pump_task, self._stderr_task):
            if t:
                t.cancel()

    def _audit(self, action: str, **kw) -> None:
        try:
            with open(config.AUDIT_LOG, "a") as f:
                parts = " ".join(f"{k}={v}" for k, v in kw.items())
                f.write(f"{time.time():.0f} {action} lane={self.lane.name} "
                        f"session={self.session_id} {parts}\n")
        except Exception:  # noqa: BLE001
            pass
