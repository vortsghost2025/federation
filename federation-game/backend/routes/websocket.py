"""WebSocket route for real-time Federation state updates."""

import logging
from typing import List

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter(prefix="", tags=["websocket"])

logger = logging.getLogger(__name__)


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
            except Exception:
                logger.debug(
                    "WebSocket broadcast failed for a connection; likely disconnected"
                )


manager = ConnectionManager()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    from routes.core import get_state

    await manager.connect(websocket)
    try:
        await websocket.send_json({"type": "state", "data": await get_state()})
        while True:
            data = await websocket.receive_json()
            if data.get("action") == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        manager.disconnect(websocket)
