from fastapi import APIRouter, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.campuses.schemas import campus_to_public
from app.db import get_db
from app.deps import get_current_user

router = APIRouter(prefix="/campuses", tags=["campuses"])


@router.get("")
async def list_campuses(
    _user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    campuses = await db.campuses.find().sort("name", 1).to_list(length=None)
    return [campus_to_public(c) for c in campuses]
