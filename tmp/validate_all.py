import ast

files = [
    r"S:\federation\federation-game\backend\faction_diplomacy.py",
    r"S:\federation\federation-game\backend\autonomous_choice_resolver.py",
    r"S:\federation\federation-game\backend\nvidia_nim_client.py",
    r"S:\federation\federation-game\backend\npc_autonomy.py",
]
for f in files:
    try:
        with open(f, encoding="utf-8") as fh:
            ast.parse(fh.read())
        print(f"VALID: {f.split(chr(92))[-1]}")
    except SyntaxError as e:
        print(f"FAIL: {f.split(chr(92))[-1]} - Line {e.lineno}: {e.msg}")
