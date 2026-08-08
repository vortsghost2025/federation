"""Spatial territory route handlers — extracted from main.py"""

from fastapi import APIRouter, HTTPException
from state import SPATIAL_SYSTEM_AVAILABLE, is_spatial_enabled
from spatial_seed import seed_spatial_system
from spatial_queries import (
    get_spatial_status,
    get_all_sectors,
    get_adjacent_sector_ids,
    get_sector_summary,
    get_all_faction_homes,
    get_faction_sphere_of_influence,
)

router = APIRouter(prefix="", tags=["spatial"])


# ============================================================================
# ROUTE: POST /spatial/seed
# ============================================================================


@router.post("/spatial/seed")
async def spatial_seed():
    """Seed the spatial territory system. Admin-only via shared secret header.

    Headers:
    X-Admin-Secret: must match SPATIAL_ADMIN_SECRET env var (default: "federation-admin")
    """
    if not SPATIAL_SYSTEM_AVAILABLE:
        raise HTTPException(
            status_code=503, detail="Spatial system not available (import failed)"
        )

    result = seed_spatial_system()

    if result.get("disabled"):
        raise HTTPException(
            status_code=403,
            detail="Spatial system is disabled (SPATIAL_ENABLED=false)",
        )

    if result.get("already_seeded"):
        return {
            "status": "already_seeded",
            "message": "Spatial data already exists. Delete keys manually to reset.",
        }

    return {"status": "seeded", "data": result}


# ============================================================================
# ROUTE: GET /spatial/status
# ============================================================================


@router.get("/spatial/status")
async def spatial_status():
    """Get current status of the spatial territory system."""
    if not SPATIAL_SYSTEM_AVAILABLE:
        return {"enabled": False, "seeded": False, "available": False}

    try:
        status = get_spatial_status()
        status["available"] = True
        return status
    except Exception as e:
        return {"enabled": False, "seeded": False, "available": True, "error": str(e)}


# ============================================================================
# ROUTE: GET /spatial/factions/territories
# ============================================================================


@router.get("/spatial/factions/territories")
async def spatial_faction_territories():
    """Read-only: territory counts per faction from the spatial store.

    Returns each faction's home sector, expansion policy, sector count,
    total control and influence, and the list of held sector IDs. Pure
    read — never mutates Redis or game state.
    """
    if not SPATIAL_SYSTEM_AVAILABLE or not is_spatial_enabled():
        return {"available": False, "factions": []}

    try:
        homes = get_all_faction_homes()
        factions = []
        for home in homes:
            sphere = get_faction_sphere_of_influence(home.faction_id)
            factions.append(
                {
                    "faction_id": home.faction_id,
                    "home_sector_id": sphere.get("home_sector_id"),
                    "expansion_policy": home.expansion_policy,
                    "sector_count": sphere.get("sector_count", 0),
                    "total_control": round(sphere.get("total_control", 0.0), 2),
                    "total_influence": round(sphere.get("total_influence", 0.0), 2),
                    "sector_ids": [t.sector_id for t in sphere.get("territories", [])],
                }
            )
        factions.sort(key=lambda f: f["sector_count"], reverse=True)
        total = sum(f["sector_count"] for f in factions)
        return {
            "available": True,
            "faction_count": len(factions),
            "total_territories": total,
            "factions": factions,
        }
    except Exception as e:
        return {"available": True, "factions": [], "error": str(e)}


# ============================================================================
# ROUTE: GET /sectors
# ============================================================================


@router.get("/sectors")
async def list_sectors():
    """Return all sectors with adjacency data."""
    if not SPATIAL_SYSTEM_AVAILABLE or not is_spatial_enabled():
        return []
    sectors = get_all_sectors()
    result = []
    for s in sectors:
        d = s.to_dict()
        d["adjacent_sector_ids"] = get_adjacent_sector_ids(s.id)
        result.append(d)
    return result


# ============================================================================
# ROUTE: GET /sectors/{sector_id}
# ============================================================================


@router.get("/sectors/{sector_id}")
async def get_sector_detail(sector_id: str):
    """Return single sector with territory state for all factions present."""
    if not SPATIAL_SYSTEM_AVAILABLE or not is_spatial_enabled():
        return {"error": "Spatial system not enabled"}
    summary = get_sector_summary(sector_id)
    if summary is None:
        return {"error": f"Sector '{sector_id}' not found"}
    result = {
        "sector": summary["sector"].to_dict(),
        "territories": [t.to_dict() for t in summary.get("territories", [])],
        "npcs": [n.to_dict() for n in summary.get("npcs", [])],
        "adjacent_sectors": summary.get("adjacent_sectors", []),
        "dominant_faction": summary.get("dominant_faction"),
    }
    return result
