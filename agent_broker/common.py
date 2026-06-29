"""Configuração e helpers compartilhados do Broker A2A."""
from __future__ import annotations

import os
import secrets
from pathlib import Path

BASE = Path(os.path.expanduser("~/.local/share/agent-broker"))
STATE = BASE / "state"
INBOX_DIR = STATE / "inbox"
REGISTRY = STATE / "registry.json"
ENV_FILE = STATE / ".env"

HOST = "127.0.0.1"
PORT = int(os.environ.get("BROKER_PORT", "3470"))

# Liveness
HEARTBEAT_TTL = 120          # s sem heartbeat => agente considerado offline
SWEEP_INTERVAL = 30          # s entre varreduras de TTL

# Controle do ask síncrono
MAX_ASK_DEPTH = 3            # nº máximo de asks aninhados em voo (corta ciclos/runaway)
ASK_TIMEOUT_DEFAULT = 60
ASK_TIMEOUT_CAP = 300

LANES = ["original", "go", "zen", "nv"]

# Session Gateway (para entregar asks síncronos)
GW_URL = os.environ.get("SESSION_GATEWAY_URL", "http://127.0.0.1:3471")
GW_TOKEN_FILE = Path(os.path.expanduser("~/.config/session-gateway/token"))


def ensure_dirs() -> None:
    INBOX_DIR.mkdir(parents=True, exist_ok=True)


def get_or_create_token() -> str:
    """Bearer token do broker, persistido em state/.env (compartilhado com o shim)."""
    ensure_dirs()
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            if line.startswith("BROKER_TOKEN="):
                return line.split("=", 1)[1].strip()
    tok = secrets.token_hex(32)
    ENV_FILE.write_text(f"BROKER_TOKEN={tok}\n")
    ENV_FILE.chmod(0o600)
    return tok


def gateway_token() -> str | None:
    try:
        return GW_TOKEN_FILE.read_text().strip()
    except OSError:
        return None
