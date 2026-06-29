# Troubleshooting

### Gateway won't start / `ModuleNotFoundError`
The launchers use the system Python on purpose. If you run inside a virtualenv that
lacks the deps, install them there or run with `/usr/bin/python3`. The `bin/` scripts
already pin an absolute interpreter so they don't break inside a `.venv`.

### `Error: When using --print, --output-format=stream-json requires --verbose`
A lane `command` dropped `--verbose`. The gateway always passes it; if you wrote a
custom wrapper, make sure it forwards all args (`exec claude "$@"`), not a fixed subset.

### Session create hangs ~45s then errors with "claude saiu cedo"
The child exited during startup. Check the lane `command` runs `claude` correctly and
the backend/proxy is reachable. `GET /v1/lanes` shows `proxy_up` for lanes with a
`proxy_port`.

### Prompt returns empty / `is_error: true`, `stop_reason: process_exit`
The child crashed mid-turn (often an upstream/model error). The next prompt respawns
with `--resume`. Look at the lane's backend logs.

### A2A tools don't appear in a session
- They load at launch — **reopen** the session.
- Confirm the MCP server is **user-scoped**: `claude mcp get a2a` should say
  *"User config (available in all your projects)"*. A project-scoped `.mcp.json` entry
  needs approval and won't load headless.
- Check the shim path in `claude mcp get a2a` points to `agent_broker/a2a_shim.py`.

### `ask_agent` says `offline`
The target isn't registered (no live session, or its shim couldn't find a session id).
Targets must be running sessions that loaded the shim (heartbeat every 60s, TTL 120s).
Address by lane, display name, or exact session id.

### `ask_agent` says `busy` / `depth_exceeded`
Working as intended: one ask per target at a time, max 3 nested asks. Retry, or
restructure to avoid cycles.

### `ask_agent` returns the wrong backend's answer
The target's lane must be registered correctly so the broker resume-forks with the right
`command`. Lane is auto-derived from `ANTHROPIC_BASE_URL`; for custom backends set
`AGENT_LANE` in the wrapper, and make sure the lane exists in `lanes.json`.

### Two terminals editing one session / corrupted transcript
Never drive a `busy` discovered session. Prefer `mode: fork`. The gateway refuses to
drive sessions whose `status == "busy"`.

### Reset everything
```bash
./bin/agent-broker stop
./bin/session-gateway stop
rm -f ~/.local/share/agent-broker/state/registry.json
rm -f ~/.local/share/agent-broker/state/inbox/*.jsonl
```
