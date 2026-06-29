"""Lockfiles por sessão (flock) — evita 2 escritores no mesmo transcript."""
from __future__ import annotations

import fcntl
import json
import os
import time
from typing import Optional

from . import config


class SessionLock:
    def __init__(self, session_id: str):
        self.path = config.LOCKS_DIR / f"{session_id}.lock"
        self._fd: Optional[int] = None

    def acquire(self) -> bool:
        config.ensure_dirs()
        self._fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(self._fd)
            self._fd = None
            return False
        os.ftruncate(self._fd, 0)
        os.write(self._fd, json.dumps(
            {"owner": "gateway", "pid": os.getpid(), "since": time.time()}).encode())
        return True

    def release(self) -> None:
        if self._fd is not None:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            finally:
                os.close(self._fd)
                self._fd = None
                try:
                    os.unlink(self.path)
                except OSError:
                    pass

    def __enter__(self):
        if not self.acquire():
            raise RuntimeError(f"sessão {self.path.stem} já está travada")
        return self

    def __exit__(self, *a):
        self.release()
