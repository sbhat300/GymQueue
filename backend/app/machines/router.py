from fastapi import APIRouter, Depends, HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.db import get_db
from app.deps import get_current_user
from app.machines.schemas import machine_to_public
from app.models.common import oid

router = APIRouter(tags=["machines"])


@router.get("/campuses/{campus_id}/machines")
async def list_machines(
    campus_id: str,
    _user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    machines = await db.machines.find({"campus_id": oid(campus_id, "campus_id")}).sort("name", 1).to_list(length=None)
    return [machine_to_public(m) for m in machines]


@router.get("/machines/{machine_id}")
async def get_machine(
    machine_id: str,
    _user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    machine = await db.machines.find_one({"_id": oid(machine_id, "machine_id")})
    if machine is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Machine not found")
    return machine_to_public(machine)
