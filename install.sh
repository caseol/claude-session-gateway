#!/usr/bin/env bash
# Deploys the launchers + A2A broker and registers the MCP shim user-scoped.
# Idempotent. The Session Gateway itself can also run straight from the repo
# (./bin/session-gateway start) without installing.
set -e

REPO="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
BIN="$HOME/.local/bin"
BROKER_DIR="$HOME/.local/share/agent-broker"
CFG="$HOME/.config/session-gateway"

mkdir -p "$BIN" "$BROKER_DIR/state/inbox" "$CFG"

# Record repo location so installed launchers find the package.
echo "SESSION_GATEWAY_HOME=$REPO" > "$CFG/env"

# Lane config (don't overwrite an existing one).
if [ ! -f "$CFG/lanes.json" ]; then
  cp "$REPO/config/lanes.example.json" "$CFG/lanes.json"
  echo "criado $CFG/lanes.json (edite para adicionar lanes)"
fi

# Deploy launchers.
for f in session-gateway agent-broker claude-orig _a2a_common.sh; do
  install -m 0755 "$REPO/bin/$f" "$BIN/$f"
done

# Deploy broker code (state stays under ~/.local/share/agent-broker/state).
cp "$REPO/agent_broker/"*.py "$BROKER_DIR/"

# Register the A2A MCP shim user-scoped (so every session gets the tools).
if command -v claude >/dev/null 2>&1; then
  claude mcp remove a2a -s user >/dev/null 2>&1 || true
  claude mcp add -s user a2a -- /usr/bin/python3 "$BROKER_DIR/a2a_shim.py" \
    && echo "MCP a2a registrado (user scope)" \
    || echo "aviso: 'claude mcp add' falhou — registre o A2A manualmente"
else
  echo "aviso: 'claude' não encontrado no PATH — A2A não registrado"
fi

echo
echo "Pronto. Para iniciar:"
echo "  session-gateway start"
echo "  agent-broker start         # opcional (A2A)"
echo "Garanta que ~/.local/bin está no PATH."
