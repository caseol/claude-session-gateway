# Architecture

## Overview

```
  Your app ──HTTP──► Session Gateway (3471) ──spawn/stream-json──► claude (lane)
                          ▲                                            │
  Agent A ──MCP tool──► a2a_shim ──HTTP──► Agent Broker (3470) ─uses Gateway┘
```

Two independent services, both `127.0.0.1`-only:

- **Session Gateway** — drive `claude` sessions over HTTP.
- **Agent Broker** (+ MCP shim) — optional A2A layer built *on top of* the Gateway.

## Session Gateway (`session_gateway/`)

FastAPI + asyncio. Modules:

| Module | Responsibility |
|---|---|
| `sdk_protocol.py` | Defensive encode/decode of Claude Code's `stream-json` (see [STREAM-JSON.md](STREAM-JSON.md)). Dispatches by `type`; terminator = `result`; tolerates unknown types and chunked lines via a byte buffer. |
| `child.py` | `PersistentClaudeChild`: an `asyncio` subprocess per session. stdin/stdout/stderr pumps, one turn in flight, per-turn permission mode via `control_request`, restart-on-crash with `--resume`. |
| `session_manager.py` | Registry of hosted sessions, lifecycle, lockfiles, permission-mode validation/gating. |
| `lanes.py` | Lane config (`~/.config/session-gateway/lanes.json`) → how to launch `claude`. |
| `resume.py` | Secondary mechanism: discover `~/.claude/sessions/*.json`, one-shot `--resume`/`--fork-session`. |
| `watch.py` | Read-only transcript tail (polling, dependency-free). |
| `locks.py` | `fcntl.flock` lockfiles per session. |
| `auth.py` / `config.py` | Bearer auth (constant-time) and configuration. |
| `routes/` | HTTP surface: `sessions`, `prompt`, `discovered`, `watch`, `lanes`. |

### The hosted-session lifecycle

1. `POST /v1/sessions` → `SessionManager.create` spawns the lane's `claude` with
   `-p --verbose --input-format stream-json --output-format stream-json
   --include-partial-messages --replay-user-messages --session-id <uuid>
   --permission-mode <mode>`.
2. **Important:** Claude Code only emits `system/init` *after* the first stdin line, so
   the gateway does **not** wait for init at spawn — it knows the session id up front
   (it passed `--session-id`). It just checks the process didn't crash early.
3. Each `prompt` writes one `{"type":"user",...}` line; the stdout pump streams the
   normalized events to the HTTP handler until the `result` terminator.
4. On crash, the next prompt respawns with `--resume <id>` (context survives).

### Why not Claude Code's native Remote Control?

`--remote-control` likely relays through Anthropic's cloud and needs real Anthropic
auth — which breaks when sessions use third-party model backends
(`ANTHROPIC_AUTH_TOKEN=unused`). The `stream-json` approach is provider-agnostic.

## Agent Broker (`agent_broker/`)

- `broker.py` (port 3470, FastAPI) — agent **registry keyed by `session_id`** (so
  multiple agents can share a lane), per-agent **inboxes** (append-only JSONL with
  read tombstones), and **sync `ask` routing** that calls the Gateway to resume-fork
  the target. Guards: global in-flight depth cap, per-target lock, layered timeouts.
- `a2a_shim.py` — a stdlib-only stdio **MCP server** loaded into every `claude`
  session. Exposes the A2A tools and forwards them to the broker. Auto-discovers its
  identity (lane from `ANTHROPIC_BASE_URL`, session id from `~/.claude/sessions/<ppid>.json`,
  token from `state/.env`). Honors `A2A_NO_SHIM=1` to stay inert in forks/hosted sessions.
- `common.py` — paths, token, gateway URL.

The Broker uses the Gateway's `POST /v1/discovered/{id}/prompt` (fork mode) as the
delivery mechanism, so A2A inherits the Gateway's lane/backend handling for free.

## Data on disk

| Path | What |
|---|---|
| `~/.config/session-gateway/token` | Gateway bearer token (`0600`) |
| `~/.config/session-gateway/lanes.json` | Lane config |
| `~/.config/session-gateway/locks/` | Per-session lockfiles |
| `~/.config/session-gateway/audit.log` | Spawn audit log |
| `~/.local/share/agent-broker/state/.env` | Broker token |
| `~/.local/share/agent-broker/state/registry.json` | Live agent registry |
| `~/.local/share/agent-broker/state/inbox/<session_id>.jsonl` | Async inboxes |
| `~/.claude/projects/<slug>/<session_id>.jsonl` | Claude Code transcripts (owned by Claude Code) |
| `~/.claude/sessions/<pid>.json` | Live session metadata (owned by Claude Code) |
