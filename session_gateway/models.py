"""Schemas pydantic da API."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class CreateSessionReq(BaseModel):
    lane: str = Field(..., description="original|go|zen|nv")
    cwd: Optional[str] = None
    model: Optional[str] = None
    permission_mode: Optional[str] = None
    mcp_config: Optional[list[str]] = None  # caminhos/strings JSON p/ --mcp-config


class SessionInfo(BaseModel):
    session_id: str
    lane: str
    cwd: str
    status: str               # starting|idle|busy|crashed|stopped
    transcript_path: Optional[str] = None
    started_at: float
    last_turn_at: Optional[float] = None


class PromptReq(BaseModel):
    prompt: str
    permission_mode: Optional[str] = None
    stream: bool = False


class PromptResp(BaseModel):
    session_id: str
    text: str
    stop_reason: Optional[str] = None
    is_error: bool = False
    usage: Optional[dict] = None
    cost_usd: Optional[float] = None


class DiscoveredSession(BaseModel):
    session_id: str
    pid: int
    cwd: str
    status: Optional[str] = None
    kind: Optional[str] = None
    version: Optional[str] = None
    safe_to_drive: bool = False


class DiscoveredPromptReq(BaseModel):
    prompt: str
    mode: str = "fork"           # fork (não-destrutivo) | resume
    permission_mode: Optional[str] = None
    lane: Optional[str] = None   # resume via launcher da lane (env do backend correto)


class ErrorEnv(BaseModel):
    error: dict[str, Any]
