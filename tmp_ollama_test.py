import urllib.request, json
try:
    resp = urllib.request.urlopen("http://ollama:11434/api/tags", timeout=5)
    data = json.loads(resp.read().decode())
    models = [m["name"] for m in data.get("models", [])]
    print("Ollama OK. Models:", models)
except Exception as e:
    print("Ollama FAILED:", e)
