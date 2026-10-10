from collections import defaultdict

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        self._user_connections: dict[str, set[WebSocket]] = defaultdict(set)
        self._machine_subscribers: dict[str, set[WebSocket]] = defaultdict(set)
        self._socket_user: dict[WebSocket, str] = {}
        self._socket_machines: dict[WebSocket, set[str]] = defaultdict(set)

    async def connect(self, user_id: str, ws: WebSocket) -> None:
        await ws.accept()
        self._user_connections[user_id].add(ws)
        self._socket_user[ws] = user_id

    def disconnect(self, ws: WebSocket) -> None:
        user_id = self._socket_user.pop(ws, None)
        if user_id is not None:
            self._user_connections[user_id].discard(ws)
        for machine_id in self._socket_machines.pop(ws, set()):
            self._machine_subscribers[machine_id].discard(ws)

    def subscribe_machine(self, ws: WebSocket, machine_id: str) -> None:
        self._machine_subscribers[machine_id].add(ws)
        self._socket_machines[ws].add(machine_id)

    def unsubscribe_machine(self, ws: WebSocket, machine_id: str) -> None:
        self._machine_subscribers[machine_id].discard(ws)
        self._socket_machines[ws].discard(machine_id)

    async def send_to_user(self, user_id: str, event: dict) -> None:
        dead = []
        for ws in self._user_connections.get(user_id, set()):
            try:
                await ws.send_json(event)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    async def send_to_users(self, user_ids: list[str], event: dict) -> None:
        for uid in user_ids:
            await self.send_to_user(uid, event)

    async def broadcast_to_machine(self, machine_id: str, event: dict) -> None:
        dead = []
        for ws in self._machine_subscribers.get(machine_id, set()):
            try:
                await ws.send_json(event)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


manager = ConnectionManager()
