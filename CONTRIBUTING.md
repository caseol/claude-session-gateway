# Contributing

Thanks for your interest! This is a small, focused project.

## Dev setup

```bash
python3 -m pip install -r requirements.txt
./bin/session-gateway start      # runs from the repo (location-aware)
PYTHONPATH=. python3 -m pytest tests/ -q
```

## Guidelines

- Keep it **local-first and dependency-light** (stdlib + FastAPI/httpx/uvicorn). The MCP
  shim is intentionally stdlib-only.
- Don't break the **safe defaults**: `plan` permission mode, `127.0.0.1` bind, dangerous
  modes gated behind `GW_ALLOW_DANGEROUS_MODES`.
- The `stream-json` parser must stay **defensive** (tolerate unknown event types and
  protocol drift). If you observe new event shapes, add a fixture under `tests/fixtures/`.
- Match the existing module style; keep the HTTP surface documented in `docs/API.md`.

## Testing against models

Use a **free lane** for end-to-end tests so you don't spend paid quota. The protocol
tests run offline against the fixtures.

## Before a PR

- `python3 -m pytest tests/ -q` passes.
- New endpoints/flags are documented in `README.md` + `docs/`.
- No secrets, tokens, transcripts, or machine-specific paths committed (see `.gitignore`).
