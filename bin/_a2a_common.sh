#!/usr/bin/env bash
# _a2a_common.sh — sourced pelos launchers (claude-go/zen/nv/orig) APÓS definirem
# AGENT_LANE. O shim MCP a2a é carregado GLOBALMENTE via ~/.claude/.mcp.json; aqui
# só exportamos a identidade do agente e fazemos o exec final do claude.
# Requer que o array PASSTHRU já exista no shell que faz o source.

# Turnos transitórios (forks do /ask, sessões hospedadas pelo gateway) setam
# A2A_NO_SHIM=1: o shim global ainda carrega, mas fica inerte (não registra).
if [ "${A2A_NO_SHIM:-0}" = "1" ]; then
  exec claude "${PASSTHRU[@]}"
fi

: "${AGENT_LANE:=unknown}"
export AGENT_LANE
export AGENT_SESSION_ID="${AGENT_SESSION_ID:-$(uuidgen)}"
export AGENT_DISPLAY_NAME="${AGENT_DISPLAY_NAME:-$AGENT_LANE}"
export BROKER_PORT="${BROKER_PORT:-3470}"

# Sobe broker e gateway best-effort (necessários para A2A e ask_agent síncrono)
if ! ss -tlnp "sport = :$BROKER_PORT" 2>/dev/null | grep -q LISTEN; then
  "$HOME/.local/bin/agent-broker" start >/dev/null 2>&1 || true
fi
_GW_PORT="${SESSION_GATEWAY_PORT:-3471}"
if ! ss -tlnp "sport = :$_GW_PORT" 2>/dev/null | grep -q LISTEN; then
  if command -v session-gateway >/dev/null 2>&1; then
    session-gateway start >/dev/null 2>&1 || true
  fi
fi

# Se já há uma flag de sessão nos args (--session-id/--resume/--continue), NÃO
# forçamos outro --session-id — o claude rejeita --session-id junto de
# --continue/--resume sem --fork-session. Para --session-id/--resume COM valor,
# adotamos o id como identidade A2A.
_a2a_existing=""
_a2a_has_session_flag=0
_a2a_prev=""
for _a in "${PASSTHRU[@]}"; do
  case "$_a2a_prev" in
    --session-id|--resume|-r) _a2a_existing="$_a" ;;
  esac
  case "$_a" in
    --session-id=*) _a2a_existing="${_a#--session-id=}"; _a2a_has_session_flag=1 ;;
    --resume=*)     _a2a_existing="${_a#--resume=}";     _a2a_has_session_flag=1 ;;
    --session-id|--resume|-r|--continue|-c) _a2a_has_session_flag=1 ;;
  esac
  _a2a_prev="$_a"
done

[ -n "$_a2a_existing" ] && export AGENT_SESSION_ID="$_a2a_existing"

if [ "$_a2a_has_session_flag" = "1" ]; then
  exec claude "${PASSTHRU[@]}"
else
  exec claude --session-id "$AGENT_SESSION_ID" "${PASSTHRU[@]}"
fi
