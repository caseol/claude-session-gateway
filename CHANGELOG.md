# Changelog

All notable changes to this project are documented here.

## [0.2.0] — A2A everywhere + open-source release

### Added
- **Agent-to-Agent (A2A)** layer: `agent_broker/` (broker + stdio MCP shim) exposing
  `ask_agent` (sync), `send_message`/`broadcast`/`check_inbox`/`read_messages`/`list_agents`.
- **MCP shim auto-identity**: lane derived from `ANTHROPIC_BASE_URL`, session id from
  `~/.claude/sessions/<ppid>.json`, broker token from `state/.env`. Honors `A2A_NO_SHIM=1`
  (inert in forks/hosted sessions).
- **User-scoped MCP registration** so every Claude Code session gains the A2A tools
  (project-scoped `.mcp.json` requires approval and doesn't load headless).
- **Config-driven lanes** (`~/.config/session-gateway/lanes.json`) — the gateway is no
  longer hard-coded to specific backends.
- Open-source packaging: `README`, `docs/`, `LICENSE`, `install.sh`, examples.

### Changed
- Broker registry is now keyed by **session id** (multiple agents per lane); targets
  resolve by session id → display name → lane.
- Lanes expose `command` instead of `via_launcher`/`argv0`.

## [0.1.0] — Initial gateway

### Added
- **Session Gateway** (port 3471): hosted `stream-json` sessions, sync + SSE prompts,
  per-request permission mode (via `control_request`), resume/fork of discovered
  sessions, transcript watch, bearer auth, `cwd` allowlist, dangerous-mode gating.
- Defensive `stream-json` parser calibrated against Claude Code v2.1.x.
- Protocol unit tests + calibration fixtures.
