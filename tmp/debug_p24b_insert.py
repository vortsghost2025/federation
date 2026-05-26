#!/usr/bin/env python3
"""Insert P24b debug logging into simulation_engine.py on VPS host path."""

import sys

filepath = "/docker/federation-game/backend/simulation_engine.py"

with open(filepath, "rb") as f:
    raw = f.read().replace(b"\r\n", b"\n").replace(b"\r", b"\n")

# The actual indentation is 12 spaces (3 levels: def -> try -> code)
old = (
    b'diplo_result = result.get("step8_5_diplomacy", {})\n'
    b"            bridge_result = propagate_diplomacy_events_to_npcs("
)

idx = raw.find(old)
if idx < 0:
    print("ERROR: target string not found")
    idx_partial = raw.find(b"diplo_result = result.get")
    if idx_partial >= 0:
        snippet = raw[idx_partial : idx_partial + 250]
        print("Target bytes:", repr(snippet))
    sys.exit(1)

debug_insert = (
    b'diplo_result = result.get("step8_5_diplomacy", {})\n'
    b"            # DEBUG P24b: snapshot diplo_result to Redis\n"
    b"            try:\n"
    b"                import json as _json\n"
    b'                r.set("debug_p24b_diplo", _json.dumps(diplo_result, default=str), ex=600)\n'
    b'                r.set("debug_p24b_npcs", str(len(npc_list)), ex=600)\n'
    b'                affiliated = [n for n in npc_list if n.get("affiliation")]\n'
    b'                r.set("debug_p24b_aff", str(len(affiliated)), ex=600)\n'
    b"            except Exception:\n"
    b"                pass\n"
    b"            bridge_result = propagate_diplomacy_events_to_npcs("
)

content = raw[:idx] + debug_insert + raw[idx + len(old) :]

with open(filepath, "wb") as f:
    f.write(content)

# Validate
import py_compile

try:
    py_compile.compile(filepath, doraise=True)
    print("DEBUG inserted and validated successfully")
except py_compile.PyCompileError as e:
    print(f"SYNTAX ERROR after insertion: {e}")
    sys.exit(1)
