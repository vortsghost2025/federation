#!/usr/bin/env python3
"""Add trace print statements to simulation_engine.py on VPS - safe version."""

import sys

target_file = (
    sys.argv[1]
    if len(sys.argv) > 1
    else "/docker/federation-game/backend/simulation_engine.py"
)

with open(target_file, "rb") as f:
    content = f.read()

content = content.replace(b"\r\n", b"\n").replace(b"\r", b"\n")

replacements = [
    # Trace 1: Before Step 8
    (
        b"    # Step 8: Faction autonomous tech research\n    try:",
        b"    # Step 8: Faction autonomous tech research\n    print('[TRACE] Before Step 8')\n    try:",
    ),
    # Trace 2: Before Step 8.5
    (
        b"    # Step 8.5: Faction diplomacy cycle\n    try:",
        b"    # Step 8.5: Faction diplomacy cycle\n    print('[TRACE] Before Step 8.5')\n    try:",
    ),
    # Trace 3: Inside Step 8.6 try block
    (
        b'            diplo_result = result.get("step8_5_diplomacy", {})',
        b"            print('[TRACE] Step 8.6 ENTERED')\n            diplo_result = result.get('step8_5_diplomacy', {})",
    ),
    # Trace 4: Inside Step 8.6 except block
    (
        b'            result["step8_6_diplomacy_bridge"] = {"errors": [str(exc)]}',
        b"            print('[TRACE] Step 8.6 EXCEPTION:', str(exc)[:100])\n            result['step8_6_diplomacy_bridge'] = {'errors': [str(exc)]}",
    ),
]

for i, (old, new) in enumerate(replacements, 1):
    if old in content:
        content = content.replace(old, new, 1)
        print(f"Trace {i}: inserted")
    else:
        print(f"Trace {i}: NOT FOUND")
        # Show what we're looking for
        print(f"  Looking for: {old[:80]}")

with open(target_file, "wb") as f:
    f.write(content)

import py_compile

try:
    py_compile.compile(target_file, doraise=True)
    print("Syntax validation: OK")
except py_compile.PyCompileError as e:
    print(f"Syntax validation: FAILED - {e}")
