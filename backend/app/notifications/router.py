from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.db import get_db
from app.deps import get_current_user
from app.models.common import oid
from app.notifications import voice

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("/audio/{audio_id}")
async def get_audio(audio_id: str):
    """Serves synthesized voice clips by their opaque id - unauthenticated so a plain
    <audio src> works, same tradeoff as the vision service's machine snapshot images.
    The id is an unguessable hash and the spoken text (e.g. a display name in a join
    request) is already visible to the recipient in-app, so this adds no new exposure."""
    data = voice.get_cached(audio_id)
    if data is None:
        raise HTTPException(404, "Audio not found or expired")
    return Response(data, media_type="audio/mpeg", headers={"Cache-Control": "public, max-age=86400"})


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
