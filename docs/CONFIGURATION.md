# Configuration

## Lanes — `~/.config/session-gateway/lanes.json`

A **lane** is a named way to launch `claude`. The gateway runs the lane's `command`
with its headless `stream-json` flags.

```json
{
  "default":  {"command": "claude"},
  "original": {"command": "claude"},
  "go":       {"command": "claude-go",  "proxy_port": 3457},
  "zen":      {"command": "claude-zen", "proxy_port": 3459},
  "nv":       {"command": "claude-nv",  "proxy_port": 3458}
}
```

- **`command`** — an executable on `PATH` or an absolute path. It must accept the same
  flags as `claude` and ultimately `exec` the real `claude`. Use:
  - plain `claude` for the default Anthropic backend, or
  - a **wrapper script** that exports `ANTHROPIC_BASE_URL` / model env to point at a
    different backend (e.g. a local proxy), then `exec claude "$@"`.
- **`proxy_port`** — optional; only used by `GET /v1/lanes` to report whether an
  upstream proxy is listening.

If `lanes.json` is missing, a single lane `default` (`claude`) is used.

### Example: third-party backends (OpenCode proxies)

`config/lanes.opencode.example.json` shows the author's setup, where `claude-go`,
`claude-zen`, `claude-nv` are wrapper scripts that set `ANTHROPIC_BASE_URL` to a local
translation proxy (OpenAI-compatible upstreams). Any wrapper that ends in
`exec claude "$@"` works — the gateway passes the headless flags through.

A minimal wrapper looks like:

```bash
#!/usr/bin/env bash
export ANTHROPIC_BASE_URL="http://127.0.0.1:9999"
export ANTHROPIC_AUTH_TOKEN="unused"
export ANTHROPIC_DEFAULT_SONNET_MODEL="my-model"
exec claude "$@"
```

## Environment variables

| Var | Default | Effect |
|---|---|---|
| `SESSION_GATEWAY_PORT` | `3471` | Gateway port |
| `GW_ALLOW_DANGEROUS_MODES` | `0` | If `1`, allow `acceptEdits/auto/bypassPermissions/dontAsk` (otherwise `403`) |
| `GW_TURN_TIMEOUT` | `600` | Per-turn timeout (s) |
| `GW_IDLE_REAP_SECONDS` | `0` | If `>0`, reap idle hosted children after N seconds |
| `BROKER_PORT` | `3470` | Broker port |

## Allowed working directories

`config.py: ALLOWED_CWD_ROOTS` confines session `cwd` (default `~/Workspace`, `/tmp`,
`~`). Tighten this to limit the blast radius of tool-running modes.

## Tokens

- Gateway token: `~/.config/session-gateway/token` (auto-created, `0600`).
- Broker token: `~/.local/share/agent-broker/state/.env` (auto-created).
Both are read at startup; rotate by deleting the file and restarting.
