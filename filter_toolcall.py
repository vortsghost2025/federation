import json

with open(r"S:\federation\nvidia_extract.json", "r", encoding="utf-8") as f:
    data = json.load(f)

models = data.get("models", [])
tool_models = [m for m in models if m.get("tool_call") is True]

print(f"Total nvidia models: {len(models)}")
print(f"Models with tool_call=true: {len(tool_models)}")
print()

for m in tool_models:
    name = m.get("id", "unknown")
    ctx = m.get("context_length", "?")
    out = m.get("max_output", "?")
    ic = m.get("input_cost", 0)
    oc = m.get("output_cost", 0)
    so = m.get("structured_output", False)
    print(f"{name}")
    print(f"  context={ctx}  output={out}  cost={ic}/{oc}  structured_output={so}")
