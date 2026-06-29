"""Lanes — cada lane é uma forma de lançar o `claude` (binário ou um wrapper que
seta env/backend). Config-driven: lido de ~/.config/session-gateway/lanes.json,
com um default genérico (lane 'default' = `claude` puro) quando não há config.

Exemplo de lanes.json:
{
  "default":  {"command": "claude"},
  "original": {"command": "claude"},
  "go":       {"command": "claude-go",  "proxy_port": 3457},
  "zen":      {"command": "claude-zen", "proxy_port": 3459}
}
`command` é um executável em PATH ou caminho absoluto. `proxy_port` (opcional) é
só usado em GET /v1/lanes para reportar a saúde do proxy upstream.
"""
from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass

CONFIG_FILE = os.path.expanduser("~/.config/session-gateway/lanes.json")

DEFAULT_LANES = {"default": {"command": "claude"}}


@dataclass
class Lane:
    name: str
    command: str               # executável (em PATH ou absoluto)
    proxy_port: int | None = None


def _load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            data = json.load(open(CONFIG_FILE))
            if isinstance(data, dict) and data:
                return data
        except Exception:  # noqa: BLE001
            pass
    return DEFAULT_LANES


def _build() -> dict[str, Lane]:
    return {name: Lane(name, c.get("command", "claude"), c.get("proxy_port"))
            for name, c in _load_config().items()}


LANES: dict[str, Lane] = _build()


def get_lane(name: str) -> Lane:
    if name not in LANES:
        raise KeyError(f"lane desconhecida: {name!r} (válidas: {list(LANES)})")
    return LANES[name]


def resolve_command(lane: Lane) -> str:
    """Caminho absoluto do executável da lane."""
    if os.path.isabs(lane.command) and os.path.exists(lane.command):
        return lane.command
    found = shutil.which(lane.command)
    if not found:
        # tenta ~/.local/bin como fallback comum
        cand = os.path.expanduser(f"~/.local/bin/{lane.command}")
        if os.path.exists(cand):
            return cand
        raise FileNotFoundError(f"executável da lane {lane.name} não encontrado: {lane.command}")
    return found


def command_for(name: str) -> str:
    """Comando (string) configurado para uma lane pelo nome — usado pelo resume."""
    return LANES[name].command if name in LANES else "claude"
