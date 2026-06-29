# API Reference

Base URL: `http://127.0.0.1:3471` · Auth: `Authorization: Bearer <token>` on every endpoint except `/healthz`.
The token is created on first run at `~/.config/session-gateway/token` (`0600`).

Errors use the envelope `{"error": {"type": "...", "message": "..."}}` for 500s, and
FastAPI's `{"detail": "..."}` for 4xx. Status codes: `401` auth, `403` blocked mode,
`404` unknown session, `409` busy/locked, `422` bad input, `502` child/upstream failure.

---

## Health & lanes

### `GET /healthz`
No auth. → `{"ok": true, "sessions": <n>, "allow_dangerous_modes": <bool>}`

### `GET /v1/lanes`
List configured lanes and upstream proxy health.
→ `[{"lane": "zen", "command": "claude-zen", "proxy_port": 3459, "proxy_up": true}, ...]`

---

## Hosted sessions (primary mechanism)

A hosted session is a long-lived `claude` process the gateway owns and drives over
`stream-json`. Context accumulates across turns; the transcript is a normal Claude
Code transcript under `~/.claude/projects/<slug>/<session_id>.jsonl`.

### `POST /v1/sessions`
Create a session.

```jsonc
{
  "lane": "zen",                 // required; must exist in lanes.json
  "cwd": "/tmp/demo",            // optional; default ~/Workspace; must be under an allowed root
  "model": "sonnet",             // optional; passed as --model
  "permission_mode": "plan",     // optional; default "plan"
  "mcp_config": ["..."]          // optional; extra --mcp-config entries
}
```
→ `SessionInfo`:
```jsonc
{ "session_id": "<uuid>", "lane": "zen", "cwd": "/tmp/demo",
  "status": "idle", "transcript_path": "/home/.../<uuid>.jsonl",
  "started_at": 1730000000.0, "last_turn_at": null }
```

### `GET /v1/sessions`
→ array of `SessionInfo`. `status` ∈ `starting|idle|busy|crashed|stopped`.

### `GET /v1/sessions/{id}`
→ `SessionInfo` or `404`.

### `DELETE /v1/sessions/{id}`
Graceful stop (close stdin → wait → terminate → kill). → `{"stopped": "<id>"}`.

### `POST /v1/sessions/{id}/prompt`
Send one turn. Serialized per session (one turn in flight).

```jsonc
{ "prompt": "...", "permission_mode": "plan", "stream": false }
```

- `permission_mode` (optional) overrides the mode **for this turn** via a `control_request`
  on the session's stdin (validated; dangerous modes gated → `403`).
- **`stream: false`** → buffers until the turn's `result`:
  ```jsonc
  { "session_id": "...", "text": "...", "stop_reason": "end_turn",
    "is_error": false, "usage": {...}, "cost_usd": 0.0 }
  ```
- **`stream: true`** → `text/event-stream`. Event names: `text_delta`, `thinking_delta`,
  `message`, `user`, `status`, `result`, `error`. Each `data:` is
  `{"kind","text","session_id","meta"}`. The stream ends after one `result`.

If the child crashed, the next prompt transparently respawns it with `--resume <id>`
(context preserved). A turn that ends on process exit returns `is_error: true`.

---

## Discovered sessions (secondary mechanism)

Reach Claude Code sessions you already have open in a terminal.

### `GET /v1/discovered`
Reads `~/.claude/sessions/<pid>.json`.
→ `[{"session_id","pid","cwd","status","kind","version","safe_to_drive"}]`
`safe_to_drive` is true only when the pid is alive **and** `status == "idle"`.

### `POST /v1/discovered/{session_id}/prompt`
One-shot turn into an existing session.

```jsonc
{ "prompt": "...", "mode": "fork", "permission_mode": "plan", "lane": "zen" }
```
- `mode: "fork"` (**default, recommended**) → `claude --resume <id> --fork-session`:
  reads the transcript, branches to a **new** session, never writes the original.
- `mode: "resume"` → appends to the original transcript. Requires a lock and a
  re-check that the session is idle; `409` otherwise. Best-effort, not race-free.
- `lane` (optional) → resume via that lane's command, so the correct model backend
  is used (defaults to plain `claude`).
→ the raw `--output-format json` result object from Claude Code.

---

## Watch

### `GET /v1/sessions/{id}/watch` · `GET /v1/discovered/{session_id}/watch`
SSE tail of the transcript `.jsonl`. Each `data:` is one transcript record (parsed JSON).
Read-only — safe even against a busy session. Query `?from_start=true` to replay from
the beginning.

---

## Notes

- All long operations honor `GW_TURN_TIMEOUT` (default 600s).
- The gateway never drives a discovered session whose `status == "busy"`.
- Concurrency: a second prompt to a busy hosted session waits for the in-flight turn.
