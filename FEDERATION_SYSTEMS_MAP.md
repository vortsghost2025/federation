# FEDERATION SYSTEMS MAP

## 1️⃣ Source Modules
- `backend/main.py` – imports: json, random, asyncio, datetime, typing, fastapi, pydantic, sys, os, uvicorn
- `generate_map.py` – imports: __future__, ast, json, re, subprocess, pathlib, typing
- `test_live_state.py` – imports: json, sys, urllib

## 2️⃣ Static Assets (HTML/CSS/JS)
Classification: STATIC_ASSET – live status: UNKNOWN unless linked by a deployed route/page
- `frontend/index.html`

## 3️⃣ Docs / Config Files
Classification: DOC_OR_CONFIG – not considered live usage
- `FEDERATION_REPO_SYSTEMS_MAP.md`
- `FEDERATION_SYSTEMS_MAP.md`
- `systems.json`

## 4️⃣ Test Suite
- `test_live_state.py` – 0 test function(s)

## 5️⃣ FastAPI Endpoints
- `GET /` (defined in `backend/main.py`)
- `GET /state` (defined in `backend/main.py`)
- `GET /atlas` (defined in `backend/main.py`)
- `GET /engine-status` (defined in `backend/main.py`)
- `GET /event` (defined in `backend/main.py`)
- `POST /choose/{choice_id}` (defined in `backend/main.py`)
- `POST /reset` (defined in `backend/main.py`)
- `GET /log` (defined in `backend/main.py`)
- `WEBSOCKET /ws` (defined in `backend/main.py`)

## 6️⃣ Import Graph (who imports whom)
- `backend/main.py` → json, random, asyncio, datetime, typing, fastapi, pydantic, sys, os, uvicorn
- `generate_map.py` → __future__, ast, json, re, subprocess, pathlib, typing
- `test_live_state.py` → json, sys, urllib

## 7️⃣ Parse Errors