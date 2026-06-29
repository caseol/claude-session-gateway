"""Configuração do Session Gateway. Tudo em ~/.config/session-gateway/."""
from __future__ import annotations

import os
import secrets
from pathlib import Path

CONFIG_DIR = Path(os.path.expanduser("~/.config/session-gateway"))
TOKEN_FILE = CONFIG_DIR / "token"
LOCKS_DIR = CONFIG_DIR / "locks"
AUDIT_LOG = CONFIG_DIR / "audit.log"

HOST = "127.0.0.1"
PORT = int(os.environ.get("SESSION_GATEWAY_PORT", "3471"))

# Modos de permissão aceitos pelo CLI (claude --permission-mode ...)
VALID_PERMISSION_MODES = {
    "default", "plan", "acceptEdits", "auto", "bypassPermissions", "dontAsk",
}
# Modo seguro padrão para qualquer requisição que não especifique.
DEFAULT_PERMISSION_MODE = "plan"
# Modos que executam/alteram coisas; só liberados se ALLOW_DANGEROUS_MODES.
DANGEROUS_MODES = {"acceptEdits", "auto", "bypassPermissions", "dontAsk"}
ALLOW_DANGEROUS_MODES = os.environ.get("GW_ALLOW_DANGEROUS_MODES", "0") == "1"

# Raízes permitidas para cwd das sessões (limita o raio de ação de ferramentas).
ALLOWED_CWD_ROOTS = [
    Path(os.path.expanduser("~/Workspace")),
    Path("/tmp"),
    Path(os.path.expanduser("~")),
]

# Tempo (s) sem turnos antes de reapear um child ocioso. 0 = nunca.
IDLE_REAP_SECONDS = int(os.environ.get("GW_IDLE_REAP_SECONDS", "0"))

# Timeout default de um turno (s).
TURN_TIMEOUT_SECONDS = int(os.environ.get("GW_TURN_TIMEOUT", "600"))


def ensure_dirs() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    LOCKS_DIR.mkdir(parents=True, exist_ok=True)


def get_or_create_token() -> str:
    """Lê o bearer token; cria (0600) no primeiro uso."""
    ensure_dirs()
    if TOKEN_FILE.exists():
        return TOKEN_FILE.read_text().strip()
    tok = secrets.token_hex(32)
    TOKEN_FILE.write_text(tok)
    TOKEN_FILE.chmod(0o600)
    return tok


def cwd_allowed(cwd: str) -> bool:
    try:
        p = Path(cwd).resolve()
    except Exception:
        return False
    return any(str(p) == str(r) or str(p).startswith(str(r) + os.sep)
               for r in ALLOWED_CWD_ROOTS)
