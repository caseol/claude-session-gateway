# Claude Code `stream-json` protocol notes

Empirically calibrated against Claude Code `v2.1.x`. These are the facts the gateway's
parser (`session_gateway/sdk_protocol.py`) relies on. Raw fixtures: `tests/fixtures/`.

## Launch (headless, persistent)

```
claude -p --verbose \
  --input-format stream-json --output-format stream-json \
  --include-partial-messages --replay-user-messages \
  [--session-id <uuid>] --permission-mode <mode> [--mcp-config <json>]
```

- **`--verbose` is mandatory** with `--print` + `--output-format=stream-json`
  (otherwise: *"Error: When using --print, --output-format=stream-json requires --verbose"*).
- A wrapper launcher prints a banner to **stdout** before `claude` starts — the parser
  must skip non-JSON lines until the first `{`.
- `system/init` is emitted **only after the first stdin line**, so don't block waiting
  for it at spawn. Pass `--session-id` and you already know the id.

## Input (stdin, JSONL — one object per line)

```json
{"type":"user","message":{"role":"user","content":"<text>"}}
```
Do **not** close stdin (closing ends the session).

## Output (stdout, JSONL) — discriminated by `type`

| `type` | Meaning |
|---|---|
| `system` / `subtype=init` | Has `session_id`, `model`, `permissionMode`, `cwd`, `tools`, `mcp_servers`, `memory_paths`. Source of the session id. |
| `system` / `subtype=status` | Status updates. |
| `stream_event` | Wraps an Anthropic SSE event in `event` (from `--include-partial-messages`). Text deltas at `event.delta.text` when `event.type=="content_block_delta"` and `event.delta.type=="text_delta"`. |
| `user` | Replayed (`isReplay`) and synthetic (`isSynthetic`, e.g. tool results) user turns. |
| `assistant` | A complete assistant message at `message.content[*].text` (+ `model`, `stop_reason`, `usage`). |
| `result` / `subtype=success\|error_*` | **Turn terminator.** Fields: `result` (final text), `stop_reason`, `is_error`, `api_error_status`, `usage`, `total_cost_usd`, `num_turns`, `duration_ms`. |
| `control_response` | Reply to a `control_request` (see below). |

Text extraction summary:
- incremental → `stream_event.event.delta.text`
- full block → `assistant.message.content[].text`
- final → `result.result`
- end of turn → `type == "result"` (or process EOF = error)

## Per-turn permission mode (works)

Send before the user line:

```json
{"type":"control_request","request_id":"<id>","request":{"subtype":"set_permission_mode","mode":"<mode>"}}
```
Reply:
```json
{"type":"control_response","response":{"subtype":"success","request_id":"<id>","response":{"mode":"<mode>"}}}
```
Modes: `default | plan | acceptEdits | auto | bypassPermissions | dontAsk`.

## Parser robustness

- Split stdout on `\n` from a **byte buffer** (a read may not align to line boundaries).
- `json.loads` each line; on failure, emit a `parse_error` event, never crash.
- Dispatch on `type`; **unknown types pass through** as `raw`.
- Treat process EOF without a `result` as a turn-terminating error.
