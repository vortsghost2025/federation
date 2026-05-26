#!/usr/bin/env python3
"""Remove TRACE print statements from simulation_engine.py."""

import base64, py_compile

FILE = "/docker/federation-game/backend/simulation_engine.py"

with open(FILE, "rb") as f:
    raw = f.read()

content = raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
lines = content.split(b"\n")

# Remove lines containing TRACE print statements
trace_lines = [2241, 2272, 2294, 2305]  # 1-indexed
removed = 0
new_lines = []
for i, line in enumerate(lines):
    lineno = i + 1
    if lineno in trace_lines:
        removed += 1
        continue  # skip this line
    new_lines.append(line)

new_content = b"\n".join(new_lines)

# Write back
with open(FILE, "wb") as f:
    f.write(new_content)

# Validate syntax
py_compile.compile(FILE, doraise=True)
print(f"OK: Removed {removed} trace lines, {len(new_content)} bytes, syntax valid")
