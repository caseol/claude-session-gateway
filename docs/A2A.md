# Agent-to-Agent (A2A)

Let the Claude **agent inside one session** talk to the agent inside another. This is
an *optional* layer on top of the Session Gateway.

## Components

- **Agent Broker** (`agent_broker/broker.py`, port 3470) — registry + inboxes + routing.
- **MCP shim** (`agent_broker/a2a_shim.py`) — a stdio MCP server loaded into every
  `claude` session; exposes the tools and forwards them to the broker.
- **Launchers** (`bin/`) — `agent-broker` (daemon control), `claude-orig` (plain Claude
  + A2A), `_a2a_common.sh` (shared launcher snippet).

## Setup

```bash
./bin/agent-broker start
# register the shim as a user-scoped MCP server so EVERY session gets the tools:
claude mcp add -s user a2a -- /usr/bin/python3 "$PWD/agent_broker/a2a_shim.py"
```

`install.sh` does both. **User-scoped** matters: a project-scoped `.mcp.json` server
requires per-project approval and won't load in headless sessions; user-scoped servers
load everywhere automatically.

> A running session only gains the tools when **reopened** (MCP loads at launch).

## Tools

| Tool | Kind | Returns |
|---|---|---|
| `list_agents()` | — | online agents |
| `ask_agent(target, message, timeout_s=60)` | **sync** | `{ok, reply, from, elapsed_s}` |
| `send_message(target, message)` | async | enqueues into target's inbox |
| `broadcast(message)` | async | to all other online agents |
| `check_inbox()` | async | unread messages (no mark) |
| `read_messages(max=50)` | async | messages, marked read |

`target` resolves in order: exact **session id** → **display name** → **lane** (if
several share a lane, the most-recently-active one that isn't the caller).

## Identity auto-discovery

The shim figures out who it is, with this precedence (env wins):

- **lane** — `AGENT_LANE`, else derived from `ANTHROPIC_BASE_URL` port
  (`3457=go, 3458=nv, 3459=zen`), else `original`.
- **session id** — `AGENT_SESSION_ID`, else the `sessionId` from
  `~/.claude/sessions/<getppid()>.json` (the shim's parent is the `claude` process).
- **broker token** — `BROKER_TOKEN`, else read from the broker's `state/.env`.

This is why the shim can be registered once, user-scoped, and still identify each
session correctly. Wrapper launchers (`bin/_a2a_common.sh`) set the env explicitly for
deterministic identity.

`A2A_NO_SHIM=1` makes the shim **inert** (loads, serves tools, but does **not** register
or heartbeat). The Gateway sets this for hosted sessions and resume-forks so transient
`claude` processes don't churn the registry.

## How `ask_agent` is delivered

The broker calls the Gateway's `POST /v1/discovered/{target_session_id}/prompt` with
`mode: fork` and the target's lane. So the target answers **with its own context**, via
a non-destructive fork, and the reply flows back to the caller.

Consequence: a sync `ask_agent` to an **interactive** peer is answered by a *headless
fork* — it does **not** show up in that peer's live TUI. For the live TUI, use the async
inbox (the peer calls `check_inbox`/`read_messages` when it wants).

## Safety guards (enforced in the broker)

- **Depth** — at most `MAX_ASK_DEPTH=3` nested asks in flight → `depth_exceeded`.
- **Per-target lock** — one ask per target at a time → `busy`.
- **No self-ask** → `422`. **Offline target** → `offline`.
- **Timeouts** — broker→gateway = `timeout_s` (default 60, cap 300); shim→broker adds slack.

These bound cyclic chains (A→B→A→…) even across forks (which get fresh ids), because the
global in-flight counter and per-target locks still apply.

## Registry & inboxes

- Registry: `state/registry.json`, keyed by `session_id`, atomic writes, TTL sweep
  (120s) + 60s heartbeats from each shim.
- Inboxes: `state/inbox/<session_id>.jsonl`, append-only with read tombstones, survive
  broker restarts.

## Quick test (async, free of any model spend if you use a free lane)

```bash
BTOK=$(./bin/agent-broker token); H="Authorization: Bearer $BTOK"
# from agent zen → message agent nv's inbox:
curl -s -XPOST 127.0.0.1:3470/send -H "$H" \
  -H 'X-Agent-Lane: zen' -H 'X-Agent-Session: <zen-sid>' \
  -d '{"target":"nv","message":"hi"}'
# nv reads it:
curl -s -XPOST 127.0.0.1:3470/inbox/<nv-sid>/read -H "$H"
```

## Collaborative mode (agent→agent chaining)

By default the broker delivers `ask_agent` in **`plan`** permission mode: the target
answers with text but **cannot use tools**, so it can't itself call `ask_agent` to chain.
Direct asks and async inbox work; chains don't.

To let agents consult *each other* (A asks B, and B asks C to answer), set the delivery
permission mode so the forked target may use tools:

```
# ~/.local/share/agent-broker/state/.env
A2A_ASK_PERMISSION_MODE=bypassPermissions
```
and run the **Session Gateway** with `GW_ALLOW_DANGEROUS_MODES=1` (otherwise it 403s the
elevated mode). Restart both. Default stays `plan` (safe).

⚠️ Tradeoff: in this mode a forked target agent runs with tools enabled (Bash/edit/MCP),
so an adversarial A2A message could trigger tool use. Enable only among trusted local agents.


### Target with no conversation yet
If the target session was just opened and has **no transcript** (zero turns), the
resume-fork has nothing to resume. The gateway then falls back to a **fresh turn** in
the target's lane (a fresh agent has no prior context anyway), so `ask_agent` works
even against freshly-opened agents.

### Inbox + forks caveat
`ask_agent` answers via a non-destructive **fork** of the target (a new session id), so a
forked target's `check_inbox` reads the *fork's* inbox, not the live agent's. Async inbox
messages are meant to be read by the **live** session (the agent polling in its terminal).

## Persistent daemons (systemd --user)

Example units in `deploy/systemd/` (gateway sets `GW_ALLOW_DANGEROUS_MODES=1`):

```bash
cp deploy/systemd/*.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now session-gateway agent-broker
```
Manage with `systemctl --user {status,restart,stop}`; don't use the nohup launchers' stop.
