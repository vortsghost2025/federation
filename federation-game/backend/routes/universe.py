"""Universe asset proxy — serves generated textures for sectors/NPCs."""
import os
import logging
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse

logger = logging.getLogger(__name__)

ASSETS_DIR = "/docker/federation-game/universe/assets"
router = APIRouter(prefix="/universe", tags=["universe"])


@router.get("/assets/{asset_id}")
async def get_asset(asset_id: str):
    """Serve a generated asset by ID. Looks for {asset_id}.webp or {asset_id}.png."""
    for ext in [".webp", ".png", ".jpg", ".jpeg"]:
        path = os.path.join(ASSETS_DIR, asset_id + ext)
        if os.path.isfile(path):
            return FileResponse(path, media_type=f"image/{ext.lstrip('.')}")
    raise HTTPException(status_code=404, detail="Asset not found")


@router.get("/systems")
async def get_universe_systems():
    """Return the procedural universe.json if it exists."""
    universe_path = "/docker/federation-game/universe/universe.json"
    if os.path.isfile(universe_path):
        with open(universe_path, "r") as f:
            import json
            return json.load(f)
    return {"systems": [], "sectors": []}
