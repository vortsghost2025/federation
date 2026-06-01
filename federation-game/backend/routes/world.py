"""World state route handlers — extracted from main.py"""

from fastapi import APIRouter, HTTPException
from state import game_state

router = APIRouter(prefix="", tags=["world"])


@router.get("/world")
async def get_world_overview():
    """Compatibility summary for legacy /world health checks."""
    from npc_autonomy import get_world_state

    state = get_world_state()
    return {
        "status": "ok",
        "state": state,
        "conditions": list(state.keys()),
        "endpoints": {
            "state": "/world/state",
            "conditions": "/world/conditions",
            "history": "/world/history",
        },
    }


@router.get("/world/state")
async def get_world_state_endpoint():
    from npc_autonomy import get_world_state

    state = get_world_state()
    return {"state": state, "conditions": list(state.keys())}


@router.get("/world/conditions")
async def get_world_conditions_endpoint():
    from npc_autonomy import WORLD_CONDITIONS

    state = {}
    try:
        from npc_autonomy import get_world_state

        state = get_world_state()
    except Exception:
        pass

    result = {}
    for key, config in WORLD_CONDITIONS.items():
        result[key] = {
            "label": config["label"],
            "description": config["description"],
            "current": state.get(key, config["default"]),
            "default": config["default"],
            "min": config["min"],
            "max": config["max"],
        }
    return result


@router.get("/world/state/{condition}")
async def get_world_condition_endpoint(condition: str):
    from npc_autonomy import WORLD_CONDITIONS
    from npc_autonomy import get_world_condition

    if condition not in WORLD_CONDITIONS:
        raise HTTPException(status_code=404, detail=f"Unknown condition: {condition}")
    value = get_world_condition(condition)
    config = WORLD_CONDITIONS[condition]
    return {
        "condition": condition,
        "value": value,
        "label": config["label"],
        "description": config["description"],
        "default": config["default"],
        "min": config["min"],
        "max": config["max"],
    }


@router.post("/world/state/{condition}")
async def set_world_condition_endpoint(condition: str, value: int = None):
    from npc_autonomy import WORLD_CONDITIONS
    from npc_autonomy import set_world_condition as _set_wc

    if condition not in WORLD_CONDITIONS:
        raise HTTPException(status_code=404, detail=f"Unknown condition: {condition}")
    if value is None:
        raise HTTPException(status_code=400, detail="Missing 'value' parameter")
    config = WORLD_CONDITIONS[condition]
    clamped = max(config["min"], min(config["max"], value))
    _set_wc(condition, clamped)
    return {
        "condition": condition,
        "value": clamped,
        "previous_range": f"{config['min']}-{config['max']}",
    }


@router.get("/world/history")
async def get_world_state_history_endpoint(limit: int = 10):
    from npc_autonomy import get_world_state_history

    history = get_world_state_history(limit=limit)
    return {"history": history, "count": len(history)}
