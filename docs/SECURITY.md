# Security

This API can launch Claude Code, which can run tools (Bash, file edits, MCP). Treat the
gateway token like a shell credential.

## Controls in place

- **Local only** — binds `127.0.0.1`. No CORS. Do not expose it to a network without
  putting your own authenticated proxy in front.
- **Bearer token** — `~/.config/session-gateway/token` (`0600`), compared with
  `secrets.compare_digest`. The broker has its own token in `state/.env`.
- **Safe default permission mode** — every request defaults to `plan`: the agent reasons
  and plans but executes **no** tools/edits.
- **Dangerous modes gated** — `acceptEdits`, `auto`, `bypassPermissions`, `dontAsk` are
  refused with `403` unless the gateway is started with `GW_ALLOW_DANGEROUS_MODES=1`.
- **`cwd` allowlist** — sessions can only run under `ALLOWED_CWD_ROOTS`
  (`~/Workspace`, `/tmp`, `~` by default). Tighten in `config.py`.
- **Transcript writes** — driving an already-open terminal session defaults to `fork`
  (never writes the original transcript). `resume` requires a lock + idle re-check.
- **Audit log** — every child spawn is appended to
  `~/.config/session-gateway/audit.log` (argv, lane, cwd, mode, session id).

## Residual risks

- **TOCTOU on discovered sessions** — `resume` checks idle status with a small race
  window. Prefer `fork`.
- **A token holder can run tools** if they request a dangerous mode while
  `GW_ALLOW_DANGEROUS_MODES=1`. Keep it off unless you need it; scope `cwd`.
- **Not multi-user** — there is no per-user isolation. One machine, one trust domain.

## Hardening checklist

- [ ] Keep `GW_ALLOW_DANGEROUS_MODES=0` in normal use.
- [ ] Narrow `ALLOWED_CWD_ROOTS` to project dirs you actually use.
- [ ] Keep the token files `0600`; rotate by deleting + restarting.
- [ ] Never bind to `0.0.0.0`; if remote access is needed, front it with TLS + auth.
- [ ] Review `audit.log` periodically.
