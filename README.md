# Claude Session Gateway

**An HTTP gateway that lets any application drive a [Claude Code](https://claude.com/claude-code) session programmatically — preserving the session's context and memory — plus an optional agent-to-agent (A2A) layer so the agents inside different sessions can talk to each other.**

You talk to Claude Code from your terminal. This gateway lets *your code* talk to it the same way: send a prompt, get the response, keep the full conversation context across turns — over a simple local HTTP API.

> Status: working, tested against real Claude Code `v2.1.x`. Single-machine, `127.0.0.1`-only by design.

---

## Why

Claude Code is an interactive CLI. There was no clean way to:

- send prompts to a Claude Code session **from an app** while keeping its **context, memory (`CLAUDE.md`, `memory/`) and tools**;
- run **several Claude Code "personas"** (e.g. different model backends) and let them **consult each other** mid-task.

This project does both, using only Claude Code's own documented headless primitives (`-p`, `--input-format/--output-format stream-json`, `--resume`, `--session-id`, `--mcp-config`). No private APIs, no cloud relay.

## Key features

- **Persistent hosted sessions** — one long-lived `claude` process per session, driven over `stream-json`. Context accumulates turn after turn, exactly like a terminal session.
- **Sync and streaming** — get the full reply in one JSON response, or stream tokens over SSE.
- **Per-request permission mode** — `plan` (safe, no tools) by default; elevate per call (gated).
- **Resume / fork of existing terminal sessions** — discover the sessions you already have open and inject a one-shot turn (`fork` = non-destructive, default).
- **Live transcript watch** — tail any session's transcript over SSE (read-only, safe even mid-turn).
- **Lanes** — a lane is just "a way to launch `claude`" (a binary or a wrapper that sets a model backend/env). Fully **config-driven**.
- **Agent-to-Agent (A2A)** — an optional broker + MCP server that gives every session the tools `ask_agent` (sync), `send_message`/`broadcast`/`check_inbox`/`read_messages` (async).
- **Local & authenticated** — binds to `127.0.0.1`, bearer-token auth, no secrets in code.

## How it works

```
  Your app ──HTTP──► Session Gateway (3471) ──spawn/stream-json──► claude (lane: default/go/zen/…)
                          ▲                                              │
  Agent A ──MCP tool──► a2a_shim ──HTTP──► Agent Broker (3470) ─uses Gateway┘ (delivers to Agent B)
```

- **Session Gateway** (`session_gateway/`, port `3471`) — FastAPI/asyncio. Spawns and manages `claude` child processes, speaks `stream-json` to them, exposes the HTTP API.
- **Agent Broker** (`agent_broker/`, port `3470`) — optional. Registry of live agents + message inboxes; routes `ask_agent` through the Gateway (resume-fork of the target's session).
- **MCP shim** (`agent_broker/a2a_shim.py`) — a tiny stdio MCP server loaded into every `claude` session (user-scoped MCP) that exposes the A2A tools and forwards them to the Broker. It **auto-discovers its identity** (see [docs/A2A.md](docs/A2A.md)).

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full picture.

## Requirements

- **Claude Code** `v2.1.x` (native CLI) on `PATH` as `claude`.
- **Python 3.11+** with `fastapi`, `uvicorn`, `httpx`, `pydantic` (see `requirements.txt`).
- Linux/macOS. Uses `~/.claude/` (transcripts, sessions) and `~/.config/session-gateway/`.

## Install

```bash
git clone <your-fork-url> claude-session-gateway
cd claude-session-gateway
python3 -m pip install -r requirements.txt   # or use a venv
./install.sh                                  # optional: deploy launchers + register A2A MCP
```

`install.sh` is optional and only needed for the A2A feature (it copies `bin/` launchers to `~/.local/bin` and registers the MCP shim user-scoped). The Gateway itself runs straight from the repo.

## Quickstart

```bash
# 1) start the gateway (binds 127.0.0.1:3471, prints/creates a bearer token)
./bin/session-gateway start
TOKEN=$(cat ~/.config/session-gateway/token)
H="Authorization: Bearer $TOKEN"

# 2) create a session on the default lane
SID=$(curl -s -H "$H" -XPOST 127.0.0.1:3471/v1/sessions \
        -d '{"lane":"default","cwd":"/tmp/demo","permission_mode":"plan"}' \
        | python3 -c 'import sys,json;print(json.load(sys.stdin)["session_id"])')

# 3) talk to it — context is preserved across turns
curl -s -H "$H" -XPOST 127.0.0.1:3471/v1/sessions/$SID/prompt \
     -d '{"prompt":"My name is Sam. Reply just: ok"}'
curl -s -H "$H" -XPOST 127.0.0.1:3471/v1/sessions/$SID/prompt \
     -d '{"prompt":"What is my name?"}'          # → "Sam"
```

Stream tokens instead:

```bash
curl -N -H "$H" -XPOST 127.0.0.1:3471/v1/sessions/$SID/prompt \
     -d '{"prompt":"count to 5","stream":true}'   # text/event-stream
```

A Python client is in [`examples/python_client.py`](examples/python_client.py).

## Configuration: lanes

A **lane** maps a name to a command used to launch `claude`. Configure them in
`~/.config/session-gateway/lanes.json`:

```json
{
  "default":  {"command": "claude"},
  "go":       {"command": "claude-go",  "proxy_port": 3457},
  "zen":      {"command": "claude-zen", "proxy_port": 3459}
}
```

- `command` — an executable on `PATH` or an absolute path. Use plain `claude`, or a wrapper script that sets `ANTHROPIC_BASE_URL`/model env to target a different backend (e.g. the OpenCode proxies in [`config/lanes.opencode.example.json`](config/lanes.opencode.example.json)).
- `proxy_port` — optional, only used by `GET /v1/lanes` to report upstream health.

With no config file, a single `default` lane (`claude`) is used. See [docs/CONFIGURATION.md](docs/CONFIGURATION.md).

## API (summary)

| Method & path | Purpose |
|---|---|
| `POST /v1/sessions` | Create a persistent hosted session |
| `GET /v1/sessions` · `GET/DELETE /v1/sessions/{id}` | List / inspect / stop sessions |
| `POST /v1/sessions/{id}/prompt` | Send a turn (`stream:false` → JSON, `stream:true` → SSE) |
| `GET /v1/discovered` | List already-open terminal sessions |
| `POST /v1/discovered/{id}/prompt` | One-shot turn into an existing session (`mode: fork\|resume`) |
| `GET /v1/sessions/{id}/watch` | SSE tail of the transcript |
| `GET /v1/lanes` · `GET /healthz` | Lanes + health |

All endpoints (except `/healthz`) require `Authorization: Bearer <token>`. Full reference: [docs/API.md](docs/API.md).

## Permission modes & security

- Bearer token (`~/.config/session-gateway/token`, `0600`), `127.0.0.1`-only bind.
- **`permission_mode` per request**, default **`plan`** (the agent answers/plans but runs no tools/edits). Valid: `default|plan|acceptEdits|auto|bypassPermissions|dontAsk`.
- The "dangerous" modes (`acceptEdits/auto/bypassPermissions/dontAsk`) are **refused (403)** unless the gateway is started with `GW_ALLOW_DANGEROUS_MODES=1`.
- `cwd` is confined to an allowlist (`~/Workspace`, `/tmp`, `~` by default).
- This API can launch Claude Code, which can run tools. Treat the token like a shell credential. See [docs/SECURITY.md](docs/SECURITY.md).

## Agent-to-Agent (A2A)

Optional. After `./install.sh`, every Claude Code session gains MCP tools:

- `ask_agent(target, message, timeout_s)` — **synchronous**: the target answers *with its own context*, reply returned to the caller.
- `send_message(target, message)` / `broadcast(message)` — **asynchronous** (inbox).
- `check_inbox()` / `read_messages()` / `list_agents()`.

A target can be addressed by lane, display name, or session id. Sync delivery uses a **non-destructive fork** of the target's session. Cycle/depth/concurrency guards prevent runaway chains. Full design, identity auto-discovery, and nuances: [docs/A2A.md](docs/A2A.md).

## Nuances & limitations (read this)

- **One process can't be both a TUI and stdin-driven.** Hosted sessions are headless; "watch" them via the transcript SSE, or `--resume` them in a terminal when the hosted process is stopped.
- **`ask_agent` to an interactive peer answers via a headless fork** — it does *not* appear in that peer's live TUI. For the live TUI, use the async inbox (the peer reads when it wants).
- **Two writers corrupt a transcript.** Driving an already-open terminal session defaults to `fork` (never writes the original). `resume` is best-effort (lock + idle re-check), not race-free.
- **`--output-format stream-json` requires `--verbose`** and the launcher banner is skipped by the parser (see [docs/STREAM-JSON.md](docs/STREAM-JSON.md)).
- **The current session won't gain new MCP tools until reopened** (MCP loads at launch).
- Single-machine, `127.0.0.1` only. Not hardened for multi-user or network exposure.

More in [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).

## Project layout

```
session_gateway/      # the Gateway (FastAPI): protocol, child mgmt, routes, lanes
agent_broker/         # A2A broker + MCP shim (optional feature)
bin/                  # launchers: session-gateway, agent-broker, claude-orig, _a2a_common.sh
config/               # lanes.json examples
docs/                 # architecture, API, configuration, A2A, stream-json, security, troubleshooting
examples/             # python client, curl snippets
tests/                # protocol unit tests + calibration fixtures
```

## License

MIT — see [LICENSE](LICENSE).

## Acknowledgements

Built on the headless/SDK surface of Anthropic's Claude Code. Not affiliated with Anthropic.
