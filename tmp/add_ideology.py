#!/usr/bin/env python3
"""Add ideology field to npc_list in main.py on VPS."""

import base64, py_compile

FILE = "/docker/federation-game/backend/main.py"

with open(FILE, "rb") as f:
    raw = f.read()

content = raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")

# Add import of FACTION_IDEOLOGY at the top of main.py
# Find existing faction_ai import
old_import = b"from faction_ai import"
if old_import in content:
    # Find the full import line
    idx = content.find(old_import)
    line_end = content.find(b"\n", idx)
    existing_import = content[idx:line_end]
    print(f"Existing faction_ai import: {existing_import.decode()}")

    # Check if FACTION_IDEOLOGY is already imported
    if b"FACTION_IDEOLOGY" in existing_import:
        print("FACTION_IDEOLOGY already imported in main.py")
    else:
        # Add FACTION_IDEOLOGY to existing import
        # Find what's currently imported
        # The import might be multi-line or single-line
        # Safer: just add a new import line after the existing one
        new_import_line = b"from faction_ai import FACTION_IDEOLOGY"
        # Check if it already exists anywhere
        if new_import_line not in content:
            content = (
                content[: line_end + 1]
                + new_import_line
                + b"\n"
                + content[line_end + 1 :]
            )
            print("Added FACTION_IDEOLOGY import")

# Now add ideology field to npc_list construction
# Find the affiliation line and add ideology after it
old_affiliation = b'                    "affiliation": character.affiliation,'
new_affiliation = b'                    "affiliation": character.affiliation,\n                    "ideology": FACTION_IDEOLOGY.get(character.affiliation, "diplomatic") if character.affiliation else None,'

if old_affiliation in content:
    content = content.replace(old_affiliation, new_affiliation, 1)
    print("Added ideology field to npc_list")
elif b'"ideology"' in content:
    print("ideology field already exists in npc_list")
else:
    print("WARNING: Could not find affiliation line to add ideology after")

# Write back
with open(FILE, "wb") as f:
    f.write(content)

# Validate syntax
py_compile.compile(FILE, doraise=True)
print(f"OK: {len(content)} bytes, syntax valid")
