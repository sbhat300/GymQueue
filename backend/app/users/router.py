from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.db import get_db
from app.deps import get_current_user
from app.users.schemas import SetProfileRequest, user_to_public
from app.vision import enroll_client

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me")
async def get_me(user: dict = Depends(get_current_user)):
    return user_to_public(user)


@router.patch("/me/profile")
async def set_profile(
    body: SetProfileRequest,
    user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    await db.users.update_one(
        {"_id": user["_id"]},
        {"$set": {"display_name": body.display_name.strip(), "onboarding_complete": True, "updated_at": now}},
    )
    user["display_name"] = body.display_name.strip()
    user["onboarding_complete"] = True
    return user_to_public(user)


@router.delete("/me/face")
async def delete_my_face(
    user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Delete the user's face data from the vision service. They'll need to scan again before
    joining a queue. If the vision service can't confirm the delete, this fails (503) rather
    than claiming the data is gone."""
    await enroll_client.delete_face(str(user["_id"]))
    await db.users.update_one({"_id": user["_id"]}, {"$set": {"face_enrolled": False}})
    user["face_enrolled"] = False
    return user_to_public(user)
