from fastapi import APIRouter, Depends, HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.db import get_db
from app.deps import get_current_user
from app.models.common import QueueState, oid
from app.stats import service
from app.vision.service import leaves_at_if_off_camera

router = APIRouter(tags=["stats"])


@router.get("/machines/{machine_id}/stats")
async def machine_stats(
    machine_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    machine = await db.machines.find_one({"_id": oid(machine_id, "machine_id")})
    if machine is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Machine not found")

    my_active_entry = await db.queue_entries.find_one(
        {"machine_id": machine["_id"], "user_ids": user["_id"], "state": QueueState.ACTIVE.value}
    )
    leaves_at = leaves_at_if_off_camera(machine_id, str(user["_id"])) if my_active_entry else None

    return {
        **await service.machine_now(db, machine),
        "local_hour": service.local_now().hour,  # in the gym's timezone
        "busy_today": await service.busy_today(db, machine["_id"]),
        "includes_demo_data": await db.machine_samples.find_one({"machine_id": machine["_id"], "synthetic": True}) is not None,
        "leaves_at": leaves_at,
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
