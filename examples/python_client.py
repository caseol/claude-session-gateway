#!/usr/bin/env python3
"""Minimal Python client for the Claude Session Gateway.

Usage:
    python3 examples/python_client.py --lane default "Hello, who are you?"
"""
import argparse
import json
import os
import urllib.request

BASE = os.environ.get("SESSION_GATEWAY_URL", "http://127.0.0.1:3471")
TOKEN = open(os.path.expanduser("~/.config/session-gateway/token")).read().strip()
H = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


def _post(path, body):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(),
                                 headers=H, method="POST")
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def create_session(lane, cwd="/tmp/demo", permission_mode="plan"):
    return _post("/v1/sessions",
                 {"lane": lane, "cwd": cwd, "permission_mode": permission_mode})


def prompt(session_id, text, permission_mode="plan"):
    return _post(f"/v1/sessions/{session_id}/prompt",
                 {"prompt": text, "permission_mode": permission_mode})


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--lane", default="default")
    ap.add_argument("--cwd", default="/tmp/demo")
    ap.add_argument("prompt")
    a = ap.parse_args()

    s = create_session(a.lane, a.cwd)
    sid = s["session_id"]
    print(f"session {sid} ({s['lane']})")
    r = prompt(sid, a.prompt)
    print("reply:", r["text"])
    # context is preserved — ask a follow-up to see it
    r2 = prompt(sid, "Summarize what I just asked in 3 words.")
    print("follow-up:", r2["text"])
