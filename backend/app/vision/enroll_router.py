"""Browser-facing face enrollment, proxied to the vision service.

The browser never talks to the vision service directly (it would need the vision
API key, and anyone could claim to be anyone). Instead it holds a GymQueue JWT, and
this router always enrolls the frames against *that* authenticated user's id - the
client has no way to request enrollment as someone else.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from app.db import get_db
from app.deps import get_current_user
from app.vision import enroll_client

router = APIRouter(prefix="/vision/enroll", tags=["vision-enroll"])

# session_id -> owning user id, so a leaked/guessed session_id from another user's
# scan can't be fed frames. Best-effort only: lost on restart, same as vision's own
# in-memory sessions.
_session_owners: dict[str, str] = {}


class FrameBody(BaseModel):
    image: str


def _check_owner(session_id: str, user_id: str) -> None:
    owner = _session_owners.get(session_id)
    if owner is not None and owner != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "enrollment session not found")


@router.post("/start")
async def enroll_start(user: dict = Depends(get_current_user)):
    user_id = str(user["_id"])
    result = await enroll_client.start(user_id, user.get("display_name") or "")
    _session_owners[result["session_id"]] = user_id
    return result


@router.post("/{session_id}/frame")
async def enroll_frame(session_id: str, body: FrameBody, user: dict = Depends(get_current_user)):
    _check_owner(session_id, str(user["_id"]))
    return await enroll_client.send_frame(session_id, body.image)


@router.post("/{session_id}/finish")
async def enroll_finish(
    session_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    _check_owner(session_id, str(user["_id"]))
    result = await enroll_client.finish(session_id)
    _session_owners.pop(session_id, None)
    await db.users.update_one({"_id": user["_id"]}, {"$set": {"face_enrolled": True}})
    return result


@router.delete("/{session_id}")
async def enroll_cancel(session_id: str, user: dict = Depends(get_current_user)):
    _check_owner(session_id, str(user["_id"]))
    _session_owners.pop(session_id, None)
    try:
        await enroll_client.cancel(session_id)
    except HTTPException:
        pass
    return {"cancelled": True}
