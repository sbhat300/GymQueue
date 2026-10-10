from fastapi import APIRouter, Depends, HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.config import settings
from app.db import get_db
from app.deps import get_current_user
from app.models.common import oid
from app.stats import service

router = APIRouter(tags=["stats"])


@router.get("/machines/{machine_id}/stats")
async def machine_stats(
    machine_id: str,
    _user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    machine = await db.machines.find_one({"_id": oid(machine_id, "machine_id")})
    if machine is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Machine not found")
    local = service.local_now()
    return {
        **await service.machine_now(db, machine),
        "local_weekday": local.weekday(),  # 0 = Monday, in the gym's timezone
        "local_hour": local.hour,
        "busy_times": await service.busy_times(db, machine["_id"]),
        "history_days": settings.stats_history_days,
        "includes_demo_data": await db.machine_samples.find_one({"machine_id": machine["_id"], "synthetic": True}) is not None,
    }


@router.get("/campuses/{campus_id}/machine-stats")
async def campus_machine_stats(
    campus_id: str,
    _user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Right-now summary for every machine on a campus (for the machine list)."""
    machines = await db.machines.find({"campus_id": oid(campus_id, "campus_id")}).to_list(length=None)
    out = []
    for m in machines:
        now = await service.machine_now(db, m)
        now.pop("entry_wait_seconds")
        out.append(now)
    return out
