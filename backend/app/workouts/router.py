from fastapi import APIRouter, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field

from app.db import get_db
from app.deps import get_current_user
from app.models.common import oid
from app.workouts import service

router = APIRouter(prefix="/workouts", tags=["workouts"])


class ManualSet(BaseModel):
    exercise: str
    reps: int = Field(ge=1, le=500)
    weight_lbs: float | None = Field(default=None, ge=0, le=2000)


@router.get("/exercises")
async def exercises(_user: dict = Depends(get_current_user)):
    return [{"key": k, "label": label, "camera_only": camera_only} for k, (label, camera_only) in service.EXERCISES.items()]


@router.get("/today")
async def today(user: dict = Depends(get_current_user), db: AsyncIOMotorDatabase = Depends(get_db)):
    day = service.today()
    return {"day": day, "entries": await service.list_day(db, user["_id"], day)}


@router.post("/today")
async def add_set(body: ManualSet, user: dict = Depends(get_current_user), db: AsyncIOMotorDatabase = Depends(get_db)):
    return await service.add_manual(db, user["_id"], body.exercise, body.reps, body.weight_lbs)


@router.delete("/entries/{entry_id}")
async def delete_set(entry_id: str, user: dict = Depends(get_current_user), db: AsyncIOMotorDatabase = Depends(get_db)):
    await service.delete_entry(db, user["_id"], oid(entry_id, "entry_id"))
    return {"deleted": entry_id}
