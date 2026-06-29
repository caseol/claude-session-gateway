"""Testa o parser defensivo contra os fixtures reais da calibração."""
import json
import os
import sys

sys.path.insert(0, os.path.expanduser("~/Workspace/session-gateway"))
from session_gateway import sdk_protocol as proto  # noqa: E402

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "zen_raw.jsonl")


def _events():
    with open(FIX) as f:
        for ln in f:
            ln = ln.strip()
            if ln:
                yield proto.parse_line(ln)


def test_preamble_skipped():
    # As 1as linhas do fixture são banner do launcher (não-JSON) → raw/preamble
    evs = list(_events())
    assert any(e.meta.get("preamble") for e in evs[:6])


def test_has_init_with_session_id():
    inits = [e for e in _events() if e.kind == "init"]
    assert len(inits) == 1
    assert inits[0].session_id


def test_text_deltas_present():
    deltas = [e for e in _events() if e.kind == "text_delta"]
    assert any(d.text for d in deltas)


def test_terminal_result():
    results = [e for e in _events() if e.kind == "result"]
    assert len(results) == 1
    assert results[0].is_terminal
    assert results[0].text == "Oi"


def test_unknown_type_does_not_crash():
    e = proto.parse_line('{"type":"banana","x":1}')
    assert e.kind == "raw"


def test_fragmented_lines_reassembled():
    lb = proto.LineBuffer()
    raw = b'{"type":"user","message":{"role":"user","content":"oi"}}\n'
    out = []
    # alimenta em pedaços de 7 bytes
    for i in range(0, len(raw), 7):
        out += list(lb.feed(raw[i:i+7]))
    assert len(out) == 1
    assert json.loads(out[0])["type"] == "user"


def test_encode_user_turn():
    b = proto.encode_user_turn("oi")
    o = json.loads(b.decode())
    assert o["type"] == "user" and o["message"]["content"] == "oi"


def test_encode_set_permission_mode():
    rid, b = proto.encode_set_permission_mode("acceptEdits")
    o = json.loads(b.decode())
    assert o["type"] == "control_request"
    assert o["request"]["mode"] == "acceptEdits"
    assert o["request_id"] == rid
