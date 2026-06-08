import urllib.request, json
resp = urllib.request.urlopen("http://localhost:8000/openapi.json", timeout=5)
d = json.loads(resp.read())
paths = list(d.get("paths", {}).keys())
print(f"Total routes: {len(paths)}")
for p in sorted(paths):
    methods = list(d["paths"][p].keys())
    print(f"  {', '.join(m.upper() for m in methods)} {p}")
