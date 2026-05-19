"""
Manager de WebSockets para notificar al companion eventos en tiempo real.

Cuando un usuario está conectado desde su PC, su companion mantiene
abierto un WebSocket a /ws/companion. Cuando llega un nuevo item al
inbox (mandado desde el móvil), le mandamos un push.
"""

import asyncio
import json
from collections import defaultdict
from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        # user_id -> set de WebSockets activos
        self.connections: dict[str, set[WebSocket]] = defaultdict(set)

    async def connect(self, user_id: str, ws: WebSocket):
        await ws.accept()
        self.connections[user_id].add(ws)

    def disconnect(self, user_id: str, ws: WebSocket):
        self.connections[user_id].discard(ws)
        if not self.connections[user_id]:
            del self.connections[user_id]

    async def send_to_user(self, user_id: str, message: dict):
        """Manda un evento JSON a todas las conexiones de un usuario."""
        if user_id not in self.connections:
            return
        dead = []
        for ws in list(self.connections[user_id]):
            try:
                await ws.send_text(json.dumps(message))
            except Exception:
                dead.append(ws)
        for d in dead:
            self.connections[user_id].discard(d)


manager = ConnectionManager()
