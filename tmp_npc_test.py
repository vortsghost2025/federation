import urllib.request, json
base = "http://localhost:8000"
endpoints = [
    ("GET", "/npcs/char_001/mood"),
    ("POST", "/npcs/char_001/mood/refresh"),
    ("GET", "/npcs/char_001/thoughts"),
    ("GET", "/npcs/char_001/actions"),
    ("GET", "/npcs/char_001/opinion?player_id=player_1"),
    ("POST", "/npcs/char_001/opinion/update?player_id=player_1&interaction=friendly"),
    ("GET", "/npcs/char_001/relationships"),
    ("GET", "/npcs/char_001/absence-report?player_id=player_1"),
]
for method, ep in endpoints:
    url = base + ep
    try:
        if method == "POST":
            req = urllib.request.Request(url, data=b"", method="POST")
            resp = urllib.request.urlopen(req, timeout=5)
        else:
            resp = urllib.request.urlopen(url, timeout=5)
        body = resp.read().decode()[:300]
        print(f"{method} {ep} -> {resp.status}: {body}")
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:200]
        print(f"{method} {ep} -> {e.code}: {body}")
    except Exception as e:
        print(f"{method} {ep} -> ERROR: {e}")
