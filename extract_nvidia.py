import json

with open(r"C:\Users\seand\AppData\Local\AgentProfiles\kilo-a\cache\kilo\models.json", "r", encoding="utf-8") as f:
    data = json.load(f)

nvidia = data.get("nvidia", {})
result = {
    "env": nvidia.get("env", "N/A"),
    "api": nvidia.get("api", "N/A"),
    "tool_call_models": []
}

models = nvidia.get("models", {})
for model_id in sorted(models.keys()):
    info = models[model_id]
    if info.get("tool_call") is True:
        limit = info.get("limit", {})
        cost = info.get("cost", {})
        result["tool_call_models"].append({
            "id": model_id,
            "context": limit.get("context", "N/A"),
            "output": limit.get("output", "N/A"),
            "cost_input": cost.get("input", "N/A"),
            "cost_output": cost.get("output", "N/A")
        })

with open(r"S:\federation\nvidia_extract.json", "w", encoding="utf-8") as f:
    json.dump(result, f, indent=2)

print("Done. Written to S:\\federation\\nvidia_extract.json")
