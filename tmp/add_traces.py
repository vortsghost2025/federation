#!/usr/bin/env python3
"""Add trace print statements to simulation_engine.py on VPS."""

import sys

target_file = (
    sys.argv[1]
    if len(sys.argv) > 1
    else "/docker/federation-game/backend/simulation_engine.py"
)

with open(target_file, "rb") as f:
    content = f.read()

content = content.replace(b"\r\n", b"\n").replace(b"\r", b"\n")

# Trace 1: Before Step 8 try block
old = b"    # Step 8: Faction autonomous tech research\n    try:"
new = b"    # Step 8: Faction autonomous tech research\n    print('[TRACE] Before Step 8 try')\n    try:"
if old in content:
    content = content.replace(old, new, 1)
    print("Trace 1: Before Step 8 - inserted")
else:
    print("Trace 1: NOT FOUND")

# Trace 2: Before Step 8.5 try block
old = b"    # Step 8.5: Faction diplomacy cycle\n    try:"
new = b"    # Step 8.5: Faction diplomacy cycle\n    print('[TRACE] Before Step 8.5 try')\n    try:"
if old in content:
    content = content.replace(old, new, 1)
    print("Trace 2: Before Step 8.5 - inserted")
else:
    print("Trace 2: NOT FOUND")

# Trace 3: Inside Step 8.6 try block - first line
old = b'            diplo_result = result.get("step8_5_diplomacy", {})'
new = b"            print('[TRACE] Step 8.6 try block ENTERED')\n            diplo_result = result.get('step8_5_diplomacy', {})"
if old in content:
    content = content.replace(old, new, 1)
    print("Trace 3: Inside Step 8.6 try - inserted")
else:
    print("Trace 3: NOT FOUND")

# Trace 4: Before Step 8.5 exception handler (to confirm try completed)
old = b'        except Exception as exc:\n            logger.error("Step 8.5 (faction diplomacy) failed:'
new = b"        except Exception as exc:\n            print('[TRACE] Step 8.5 EXCEPTION:', exc)\n            logger.error('Step 8.5 (faction diplomacy) failed:"
if old in content:
    content = content.replace(old, new, 1)
    print("Trace 4: Step 8.5 exception handler - inserted")
else:
    print("Trace 4: NOT FOUND")

# Trace 5: Inside Step 8.6 exception handler
old = b'            logger.error("Step 8.6 (diplomacy->NPC bridge) failed:'
new = b"            print('[TRACE] Step 8.6 EXCEPTION:', exc)\n            logger.error('Step 8.6 (diplomacy->NPC bridge) failed:"
if old in content:
    content = content.replace(old, new, 1)
    print("Trace 5: Step 8.6 exception handler - inserted")
else:
    print("Trace 5: NOT FOUND")

# Trace 6: After Step 8.5 try/except block, before Step 8.6
# Look for the pattern: step8_5 error append followed by blank lines then Step 8.6
old = b'result["errors"].append(f"step8_5: {exc}")\n\n\n    # Step 8.6:'
new = b'result["errors"].append(f"step8_5: {exc}")\n    print("[TRACE] After Step 8.5 try/except, about to enter Step 8.6")\n\n    # Step 8.6:'
if old in content:
    content = content.replace(old, new, 1)
    print("Trace 6: Between Step 8.5 and 8.6 - inserted")
else:
    # Try with different whitespace
    old2 = b'result["errors"].append(f"step8_5: {exc}")\n\n    # Step 8.6:'
    new2 = b'result["errors"].append(f"step8_5: {exc}")\n    print("[TRACE] After Step 8.5 try/except, about to enter Step 8.6")\n\n    # Step 8.6:'
    if old2 in content:
        content = content.replace(old2, new2, 1)
        print("Trace 6: Between Step 8.5 and 8.6 - inserted (alt)")
    else:
        print("Trace 6: NOT FOUND - searching...")
        idx = content.find(b"Step 8.6:")
        if idx >= 0:
            print(f"  Step 8.6: found at byte {idx}")
            # Show 200 bytes before it
            print(f"  Before: {content[max(0, idx - 200) : idx]}")

with open(target_file, "wb") as f:
    f.write(content)

import py_compile

try:
    py_compile.compile(target_file, doraise=True)
    print("Syntax validation: OK")
except py_compile.PyCompileError as e:
    print(f"Syntax validation: FAILED - {e}")
