"""
Federation Game Backend - API + WebSocket Server
Star Trek LCARS Interface for Kids
"""

import json
import random
import asyncio
from datetime import datetime
from typing import Optional, Dict, List, Any
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import sys
import os

app = FastAPI(title="Federation Game API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================================
# GAME STATE
# ============================================================================


class GameState:
    def __init__(self):
        self.turn = 1
        self.credits = 1000
        self.fuel = 100
        self.shields = 100
        self.hull = 100
        self.crew_morale = 80
        self.discovered_sectors = 1
        self.allies = 0
        self.technologies_unlocked = []
        self.current_event = None
        self.log: List[Dict[str, Any]] = []
        self.federation_name = "USS Federation"


game_state = GameState()

# ============================================================================
# EVENTS - Kid-friendly Star Trek scenarios
# ============================================================================

EVENTS = [
    {
        "id": "alien_contact",
        "title": "ALIEN SHIP DETECTED",
        "description": "A strange vessel approaches. They want to talk!",
        "image": "alien_ship",
        "choices": [
            {
                "id": "greet",
                "text": "HAIL THEM",
                "outcome": "friendly",
                "reward": {"allies": 1, "credits": 50},
            },
            {
                "id": "scan",
                "text": "SCAN SHIP",
                "outcome": "scan",
                "reward": {"technologies_unlocked": ["advanced_sensors"]},
            },
            {
                "id": "shields",
                "text": "RAISE SHIELDS",
                "outcome": "defensive",
                "reward": {"shields": 10},
            },
        ],
    },
    {
        "id": "nebula",
        "title": "MYSTERIOUS NEBULA",
        "description": "A colorful cloud of gas blocks your path. It could hide treasures... or dangers!",
        "image": "nebula",
        "choices": [
            {
                "id": "explore",
                "text": "FLY IN",
                "outcome": "discovery",
                "reward": {"credits": 100, "discovered_sectors": 1},
            },
            {
                "id": "scan",
                "text": "SCAN IT",
                "outcome": "scan",
                "reward": {"fuel": 20},
            },
            {"id": "avoid", "text": "GO AROUND", "outcome": "safe", "reward": {}},
        ],
    },
    {
        "id": "distress",
        "title": "DISTRESS SIGNAL",
        "description": "Someone is calling for help! Will you answer?",
        "image": "distress",
        "choices": [
            {
                "id": "help",
                "text": "ANSWER CALL",
                "outcome": "heroic",
                "reward": {"allies": 2, "crew_morale": 10},
            },
            {
                "id": "ignore",
                "text": "IGNORE",
                "outcome": "cautious",
                "reward": {"fuel": 10},
            },
        ],
    },
    {
        "id": "asteroid",
        "title": "ASTEROID FIELD",
        "description": "Rocks everywhere! Your piloting skills are needed!",
        "image": "asteroid",
        "choices": [
            {
                "id": "dodge",
                "text": "DODGE THEM",
                "outcome": "skill",
                "reward": {"credits": 30},
            },
            {
                "id": "blast",
                "text": "BLAST THEM",
                "outcome": "combat",
                "reward": {"hull": -10, "credits": 50},
            },
            {
                "id": "shields",
                "text": "SHIELDS UP",
                "outcome": "safe",
                "reward": {"shields": -5},
            },
        ],
    },
    {
        "id": "space_station",
        "title": "SPACE STATION",
        "description": "A friendly station offers repairs and supplies!",
        "image": "station",
        "choices": [
            {
                "id": "repair",
                "text": "REPAIR HULL",
                "outcome": "repair",
                "reward": {"hull": 30, "credits": -50},
            },
            {
                "id": "refuel",
                "text": "GET FUEL",
                "outcome": "refuel",
                "reward": {"fuel": 50, "credits": -30},
            },
            {
                "id": "trade",
                "text": "TRADE",
                "outcome": "trade",
                "reward": {"credits": 100, "fuel": -20},
            },
        ],
    },
    {
        "id": "anomaly",
        "title": "SPACE ANOMALY",
        "description": "Something weird is happening! Your sensors go crazy!",
        "image": "anomaly",
        "choices": [
            {
                "id": "investigate",
                "text": "INVESTIGATE",
                "outcome": "discovery",
                "reward": {
                    "technologies_unlocked": ["anomaly_research"],
                    "crew_morale": -5,
                },
            },
            {"id": "retreat", "text": "RETREAT", "outcome": "safe", "reward": {}},
        ],
    },
]

# ============================================================================
# API ENDPOINTS
# ============================================================================


@app.get("/")
async def root():
    return {"message": "Federation Game API", "status": "operational"}


@app.get("/state")
async def get_state():
    return {
        "turn": game_state.turn,
        "credits": game_state.credits,
        "fuel": game_state.fuel,
        "shields": game_state.shields,
        "hull": game_state.hull,
        "crew_morale": game_state.crew_morale,
        "discovered_sectors": game_state.discovered_sectors,
        "allies": game_state.allies,
        "technologies_unlocked": game_state.technologies_unlocked,
        "federation_name": game_state.federation_name,
    }


@app.get("/event")
async def get_random_event():
    event = random.choice(EVENTS)
    game_state.current_event = event
    return event


@app.post("/choose/{choice_id}")
async def make_choice(choice_id: str):
    if not game_state.current_event:
        raise HTTPException(status_code=400, detail="No active event")

    event = game_state.current_event
    choice = next((c for c in event["choices"] if c["id"] == choice_id), None)

    if not choice:
        raise HTTPException(status_code=400, detail="Invalid choice")

    # Apply rewards
    reward = choice.get("reward", {})
    for key, value in reward.items():
        if hasattr(game_state, key):
            current = getattr(game_state, key)
            if isinstance(current, list):
                if isinstance(value, list):
                    current.extend(value)
                else:
                    current.append(value)
            else:
                setattr(game_state, key, max(0, current + value))

    # Log the event
    log_entry = {
        "turn": game_state.turn,
        "event": event["title"],
        "choice": choice["text"],
        "outcome": choice["outcome"],
        "timestamp": datetime.now().isoformat(),
    }
    game_state.log.append(log_entry)

    # Advance turn
    game_state.turn += 1
    game_state.fuel = max(0, game_state.fuel - 5)

    # Check game over conditions
    game_over = None
    if game_state.hull <= 0:
        game_over = "HULL DESTROYED - GAME OVER"
    elif game_state.fuel <= 0:
        game_over = "OUT OF FUEL - GAME OVER"

    return {
        "outcome": choice["outcome"],
        "reward": reward,
        "game_over": game_over,
        "new_state": await get_state(),
    }


@app.post("/reset")
async def reset_game():
    global game_state
    game_state = GameState()
    return {"message": "Game reset", "state": await get_state()}


@app.get("/log")
async def get_log():
    return game_state.log[-20:]  # Last 20 entries


# ============================================================================
# WEBSOCKET FOR REAL-TIME UPDATES
# ============================================================================


class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except:
                pass


manager = ConnectionManager()


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        await websocket.send_json({"type": "state", "data": await get_state()})
        while True:
            data = await websocket.receive_json()
            if data.get("action") == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        manager.disconnect(websocket)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
