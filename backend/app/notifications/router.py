from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.db import get_db
from app.deps import get_current_user
from app.models.common import oid

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _notification_to_public(doc: dict) -> dict:
    return {
        "id": str(doc["_id"]),
        "type": doc["type"],
        "payload": doc["payload"],
        "created_at": doc["created_at"].isoformat(),
        "read_at": doc["read_at"].isoformat() if doc.get("read_at") else None,
    }


@router.get("")
async def list_notifications(
    unread: bool = False,
    limit: int = 50,
    user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    query: dict = {"user_id": user["_id"]}
    if unread:
        query["read_at"] = None
    docs = await db.notifications.find(query).sort("created_at", -1).limit(limit).to_list(length=None)
    return [_notification_to_public(d) for d in docs]


@router.post("/mark-read")
async def mark_read(
    user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    await db.notifications.update_many(
        {"user_id": user["_id"], "read_at": None},
        {"$set": {"read_at": now}},
    )
    return {"ok": True}
