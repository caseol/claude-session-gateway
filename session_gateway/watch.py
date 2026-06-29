"""Tail read-only de um transcript .jsonl, emitindo cada linha nova (SSE).
Seguro mesmo contra sessão busy (só lê o arquivo)."""
from __future__ import annotations

import asyncio
import json
import os
from typing import AsyncIterator


async def tail_transcript(path: str, from_start: bool = False,
                          poll_s: float = 0.25) -> AsyncIterator[dict]:
    # espera o arquivo existir
    for _ in range(40):
        if os.path.exists(path):
            break
        await asyncio.sleep(0.25)
    if not os.path.exists(path):
        yield {"_error": f"transcript não encontrado: {path}"}
        return

    pos = 0 if from_start else os.path.getsize(path)
    buf = b""
    while True:
        try:
            size = os.path.getsize(path)
        except OSError:
            break
        if size < pos:           # arquivo truncado/rotacionado
            pos = 0
            buf = b""
        if size > pos:
            with open(path, "rb") as f:
                f.seek(pos)
                chunk = f.read(size - pos)
                pos = f.tell()
            buf += chunk
            while True:
                nl = buf.find(b"\n")
                if nl < 0:
                    break
                line = buf[:nl].decode("utf-8", "replace").strip()
                buf = buf[nl + 1:]
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    obj = {"_raw": line}
                yield obj
        await asyncio.sleep(poll_s)
