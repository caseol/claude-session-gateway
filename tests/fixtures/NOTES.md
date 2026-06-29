# Calibração do stream-json — Claude Code v2.1.195 (lane zen, free)

Confirmado empiricamente em 2026-06-29.

## Comando de launch (headless, persistente)
```
claude -p --verbose --input-format stream-json --output-format stream-json \
       --include-partial-messages --replay-user-messages \
       [--session-id <uuid>] --permission-mode <modo> [--mcp-config <json>]
```
- **`--verbose` é OBRIGATÓRIO** com `--print` + `--output-format=stream-json` (senão: "Error: When using --print, --output-format=stream-json requires --verbose").
- Os launchers (claude-zen etc.) imprimem banner em **stdout** antes do `claude`. O parser DEVE pular linhas não-JSON até o primeiro `{`.

## Entrada (stdin, JSONL — uma linha por objeto)
- Turno do usuário: `{"type":"user","message":{"role":"user","content":"<texto>"}}`
- NÃO fechar o stdin (fecha encerra a sessão).

## Saída (stdout, JSONL) — discriminada por `type`
- `system`/`subtype=init`: traz `session_id`, `model`, `permissionMode`, `cwd`, `tools`, `mcp_servers`, `memory_paths`. **Fonte do session_id.**
- `system`/`subtype=status`: atualizações de status.
- `stream_event`: envelopa SSE Anthropic em `event` (com `--include-partial-messages`). Delta de texto em `event.delta.text` quando `event.type=="content_block_delta"` e `event.delta.type=="text_delta"`. Eventos: message_start, content_block_start, content_block_delta, content_block_stop, message_delta, message_stop.
- `user`: replay (`isReplay:true`) e sintéticos (`isSynthetic:true`).
- `assistant`: mensagem completa em `message.content[*].text` (+ `model`, `stop_reason`, `usage`).
- `result`/`subtype=success|error_*`: **TERMINADOR do turno.** Campos: `result` (texto final), `stop_reason`, `is_error`, `api_error_status`, `usage`, `total_cost_usd`, `num_turns`, `duration_ms`.

## Modo de permissão por requisição — FUNCIONA
Enviar ANTES da linha do usuário:
```
{"type":"control_request","request_id":"<id>","request":{"subtype":"set_permission_mode","mode":"<modo>"}}
```
Resposta: `{"type":"control_response","response":{"subtype":"success","request_id":"<id>","response":{"mode":"<modo>"}}}`.
→ Permite child persistente com modo variável por turno (opção (a) do plano). Modos: default|plan|acceptEdits|auto|bypassPermissions|dontAsk.

## Extração de texto (resumo p/ o parser)
- incremental: `stream_event.event.delta.text`
- bloco completo: `assistant.message.content[].text`
- final: `result.result`
- session_id: `system(init).session_id`
- fim do turno: `type=="result"` (ou EOF do processo = erro)
