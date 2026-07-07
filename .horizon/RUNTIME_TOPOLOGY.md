# Runtime Topology — Library-Lane Preflight Gate

Verified against the live runtime. **Docs (AGENTS.md) are HINTS, not truth. Runtime
inspection wins.** Run `tools/runtime-topology-check.ps1` BEFORE any
frontend / proxy / deploy patch. Builder agents may patch only after this
topology check passes.

## Verified live topology

- **Public edge router:** `federation-game-reverse-proxy-1` (image `traefik:latest`),
  ports `0.0.0.0:80->80` and `0.0.0.0:443->443` published. Terminates TLS
  (LetsEncrypt), then routes by `Host` + `PathPrefix` to backend services.
- **Frontend:** `federation-game-frontend-1` (image `federation-game-frontend`,
  container port `80/tcp`, **not** published to the host). Serves
  `simulation.html` / `simulation.js` / `*.css` via Traefik router `federation-game`
  (`Host(federation-game.deliberatefederation.cloud)`) → `federation-game-svc` → port 80.
- **Frontend files are BIND-MOUNTED, not baked:** `/docker/federation-game/public_html`
  → `/usr/share/nginx/html` `(ro)`. Edit the **host** file; never `docker cp`
  (the mount rejects writes → "device or resource busy").
- **Frontend nginx config is BIND-MOUNTED:** `/docker/federation-game/frontend/nginx-default.conf`
  → `/etc/nginx/conf.d/default.conf` `(ro)`.
- **`/npcs` (and most API paths) route Traefik → backend DIRECTLY**, bypassing the
  frontend nginx. Traefik router `fed-api` matches `PathPrefix('/npcs')` →
  `fed-api-svc` → **backend:8000**. The frontend `nginx-default.conf` can therefore
  never fix `/npcs` behaviour — it is not in that request path.
- **Backend:** `federation-game-backend-1` (image `federation-game-backend`,
  port `8000/tcp`, not published), mounts `/docker/federation-game/backend` →
  `/app` `(ro)`. Runs `uvicorn main:app --host 0.0.0.0 --port 8000`
  (**no** `--proxy-headers` / `--forwarded-allow-ips`).

## Reproducible proof commands (each claim above)

```bash
# Edge router
docker ps   # reverse-proxy-1  traefik:latest  ... 0.0.0.0:80->80, 0.0.0.0:443->443

# Frontend serves via Traefik
docker inspect federation-game-frontend-1 \
  | grep -iE 'routers.federation-game.rule|routers.federation-game.service|services.federation-game-svc'

# public_html + nginx conf are bind mounts
docker inspect federation-game-frontend-1 --format \
  '{{range .Mounts}}{{.Type}} {{.Source}} -> {{.Destination}} ({{.Mode}}) {{end}}'
# -> bind /docker/federation-game/public_html -> /usr/share/nginx/html (ro)
# -> bind /docker/federation-game/frontend/nginx-default.conf -> /etc/nginx/conf.d/default.conf (ro)

# /npcs owner: frontend nginx does NOT own it
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1/npcs/?limit=1   # 404
# backend owns it
curl -sI https://federation-game.deliberatefederation.cloud/npcs/?limit=1
# -> HTTP/2 307  server: uvicorn  location: https://.../npcs?limit=1

# backend command (no proxy-header flags)
docker inspect federation-game-backend-1 --format '{{json .Config.Cmd}}'
# -> ["uvicorn","main:app","--host","0.0.0.0","--port","8000"]
```

## Deployment method (use this; never `docker cp` into frontend)

| Target | Method | Reload |
|---|---|---|
| Frontend static (html/js/css) | edit host `/docker/federation-game/public_html/` | `docker exec federation-game-frontend-1 nginx -s reload` |
| Frontend nginx config | edit host `/docker/federation-game/frontend/nginx-default.conf` (bind ro) | `nginx -t && nginx -s reload` |
| Backend code | edit host `/docker/federation-game/backend/` (bind ro) | `docker restart federation-game-backend-1` |
| **Never** | `docker cp` into frontend (mount is busy) | — |

## Validation before saying "fixed"

- **Served == source:** `curl -s https://<host>/simulation.js \| md5sum` equals local md5.
- **Route owner:** `curl -sI https://<host>/<PATH>` → `server: uvicorn` (backend) vs `nginx` (frontend).
- **Redirect scheme:** same curl → `location:` must start `https://` (never `http://`).
- **Backend live:** `docker exec federation-game-backend-1 md5sum /app/<file>` equals host md5; `docker ps` shows healthy.

## BLOCK conditions (fail-closed) — do NOT patch if any is unknown

- BLOCK if active serving path is unknown.
- BLOCK if route owner (which container handles the path) is unknown.
- BLOCK if mount type (baked vs bind) is unknown.
- BLOCK if validation only checks source files, not the served runtime.
- BLOCK if local build and deployed build are not both considered.

## The rule

> Query runtime topology (`docker ps`, `docker inspect` mounts, Traefik labels,
> published ports, live curl headers, served-file hash) BEFORE any
> deploy / proxy / frontend patch. Docs are hints. Runtime inspection wins.
