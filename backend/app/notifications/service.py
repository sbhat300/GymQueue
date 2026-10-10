from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.models.common import EventType, oid
from app.ws.manager import ConnectionManager


def _event_envelope(event_type: EventType, payload: dict, ts: datetime) -> dict:
    return {"type": event_type.value, "ts": ts.isoformat(), "data": payload}


async def notify_users(
    db: AsyncIOMotorDatabase,
    manager: ConnectionManager,
    user_ids: list[str],
    event_type: EventType,
    payload: dict,
) -> None:
    if not user_ids:
        return
    now = datetime.now(timezone.utc)
    docs = [
        {
            "user_id": oid(uid, "user_id"),
            "type": event_type.value,
            "payload": payload,
            "created_at": now,
            "read_at": None,
            "delivered_at": now,
        }
        for uid in user_ids
    ]
    await db.notifications.insert_many(docs)

    event = _event_envelope(event_type, payload, now)
    await manager.send_to_users(user_ids, event)


async def broadcast_queue_updated(manager: ConnectionManager, machine_id: str) -> None:
    now = datetime.now(timezone.utc)
    event = _event_envelope(EventType.QUEUE_UPDATED, {"machine_id": machine_id}, now)
    await manager.broadcast_to_machine(machine_id, event)
