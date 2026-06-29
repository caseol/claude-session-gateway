#!/usr/bin/env bash
# Curl snippets for the Claude Session Gateway.
set -e
TOKEN=$(cat ~/.config/session-gateway/token)
H="Authorization: Bearer $TOKEN"
G=127.0.0.1:3471

echo "# health"
curl -s $G/healthz; echo

echo "# lanes"
curl -s -H "$H" $G/v1/lanes; echo

echo "# create session"
SID=$(curl -s -H "$H" -XPOST $G/v1/sessions \
        -d '{"lane":"default","cwd":"/tmp/demo","permission_mode":"plan"}' \
        | python3 -c 'import sys,json;print(json.load(sys.stdin)["session_id"])')
echo "session=$SID"

echo "# prompt (sync) — establishes context"
curl -s -H "$H" -XPOST $G/v1/sessions/$SID/prompt \
     -d '{"prompt":"My name is Sam. Reply just: ok"}'; echo

echo "# prompt (sync) — proves context retention"
curl -s -H "$H" -XPOST $G/v1/sessions/$SID/prompt \
     -d '{"prompt":"What is my name?"}'; echo

echo "# prompt (streaming SSE)"
curl -sN -H "$H" -XPOST $G/v1/sessions/$SID/prompt \
     -d '{"prompt":"count to 3","stream":true}'

echo "# watch the transcript (Ctrl-C to stop)"
echo "curl -sN -H \"\$H\" $G/v1/sessions/$SID/watch"

echo "# stop"
curl -s -H "$H" -XDELETE $G/v1/sessions/$SID; echo
