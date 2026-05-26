import ast

with open(
    r"S:\federation\federation-game\backend\llm_router.py", encoding="utf-8"
) as f:
    ast.parse(f.read())
print("VALID")
