from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.auth.security import decode_access_token
from app.ws.manager import manager

router = APIRouter()


@router.websocket("/ws")
async def ws_endpoint(websocket: WebSocket, token: str = Query(...)):
    user_id = decode_access_token(token)
    if user_id is None:
        await websocket.close(code=4401)
        return

    await manager.connect(user_id, websocket)
    try:
        while True:
            msg = await websocket.receive_json()
            msg_type = msg.get("type")
            machine_id = msg.get("machine_id")
            if not machine_id:
                continue
            if msg_type == "subscribe":
                manager.subscribe_machine(websocket, machine_id)
            elif msg_type == "unsubscribe":
                manager.unsubscribe_machine(websocket, machine_id)
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(websocket)
