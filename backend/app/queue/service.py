from datetime import datetime, timedelta, timezone

from bson import ObjectId
from fastapi import HTTPException, status
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.config import settings
from app.models.common import EventType, GraceReason, QueueState
from app.notifications.service import broadcast_queue_updated, notify_users
from app.vision import client as vision_client
from app.ws.manager import ConnectionManager

LIVE_STATE_VALUES = [s.value for s in (QueueState.WAITING, QueueState.GRACE, QueueState.ACTIVE, QueueState.RESTING)]
OWNER_STATE_VALUES = [s.value for s in (QueueState.GRACE, QueueState.ACTIVE, QueueState.RESTING)]


def _not_assigned() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You are not currently assigned to this machine.",
    )


def _require_member(entry: dict, user_id: ObjectId) -> None:
    if user_id not in entry["user_ids"]:
        raise _not_assigned()


async def get_live_queue_for_machine(db, machine_id: ObjectId) -> list[dict]:
    cursor = db.queue_entries.find(
        {"machine_id": machine_id, "state": {"$in": LIVE_STATE_VALUES}}
    ).sort("joined_at", 1)
    return await cursor.to_list(length=None)


async def get_entry_or_404(db, entry_id: ObjectId) -> dict:
    entry = await db.queue_entries.find_one({"_id": entry_id})
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Queue entry not found")
    return entry


async def _has_owner(db, machine_id: ObjectId) -> bool:
    doc = await db.queue_entries.find_one({"machine_id": machine_id, "state": {"$in": OWNER_STATE_VALUES}})
    return doc is not None


async def release_machine_and_promote(db, manager: ConnectionManager, machine_id: ObjectId) -> None:
    """Promote the earliest waiting entry to grace(turn_start) if the machine has no current owner.

    Safe to call redundantly/concurrently: the atomic find_one_and_update (keyed on
    expected state+version) and the partial unique index on queue_entries both guard
    against double-promotion races.
    """
    if await _has_owner(db, machine_id):
        return

    machine = await db.machines.find_one({"_id": machine_id})
    if machine is None:
        return

    candidate = await db.queue_entries.find_one(
        {"machine_id": machine_id, "state": QueueState.WAITING.value},
        sort=[("joined_at", 1)],
    )
    if candidate is None:
        return

    now = datetime.now(timezone.utc)
    grace_seconds = machine.get("grace_period_seconds") or settings.default_grace_period_seconds
    deadline = now + timedelta(seconds=grace_seconds)

    try:
        result = await db.queue_entries.find_one_and_update(
            {"_id": candidate["_id"], "state": QueueState.WAITING.value, "version": candidate["version"]},
            {
                "$set": {
                    "state": QueueState.GRACE.value,
                    "grace_reason": GraceReason.TURN_START.value,
                    "grace_deadline": deadline,
                    "updated_at": now,
                },
                "$inc": {"version": 1},
            },
            return_document=ReturnDocument.AFTER,
        )
    except DuplicateKeyError:
        return  # another promotion already claimed owner slot for this machine

    if result is None:
        return  # lost the race (state/version changed underneath us)

    user_ids = [str(u) for u in result["user_ids"]]
    await notify_users(
        db,
        manager,
        user_ids,
        EventType.YOUR_TURN,
        {
            "machine_id": str(machine_id),
            "machine_name": machine["name"],
            "queue_entry_id": str(result["_id"]),
            "grace_deadline": deadline.isoformat(),
            "grace_period_seconds": grace_seconds,
        },
    )
    await broadcast_queue_updated(manager, str(machine_id))


async def join_queue(db, manager: ConnectionManager, machine_id: ObjectId, user_id: ObjectId) -> dict:
    machine = await db.machines.find_one({"_id": machine_id})
    if machine is None or not machine.get("is_active", True):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Machine not found")

    existing = await db.queue_entries.find_one(
        {"user_ids": user_id, "state": {"$in": LIVE_STATE_VALUES}}
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You already have an active queue entry on a machine.",
        )

    now = datetime.now(timezone.utc)
    doc = {
        "machine_id": machine_id,
        "user_ids": [user_id],
        "state": QueueState.WAITING.value,
        "grace_reason": None,
        "joined_at": now,
        "active_started_at": None,
        "grace_deadline": None,
        "rest_started_at": None,
        "rest_deadline": None,
        "rest_count": 0,
        "version": 0,
        "created_at": now,
        "updated_at": now,
    }
    result = await db.queue_entries.insert_one(doc)
    doc["_id"] = result.inserted_id

    await release_machine_and_promote(db, manager, machine_id)
    await broadcast_queue_updated(manager, str(machine_id))

    return await db.queue_entries.find_one({"_id": doc["_id"]})


async def _start_end_of_use_grace(db, manager: ConnectionManager, entry: dict) -> dict:
    machine = await db.machines.find_one({"_id": entry["machine_id"]})
    grace_seconds = (machine.get("grace_period_seconds") if machine else None) or settings.default_grace_period_seconds
    now = datetime.now(timezone.utc)
    deadline = now + timedelta(seconds=grace_seconds)

    result = await db.queue_entries.find_one_and_update(
        {
            "_id": entry["_id"],
            "state": {"$in": [QueueState.ACTIVE.value, QueueState.RESTING.value]},
            "version": entry["version"],
        },
        {
            "$set": {
                "state": QueueState.GRACE.value,
                "grace_reason": GraceReason.END_OF_USE.value,
                "grace_deadline": deadline,
                "rest_started_at": None,
                "rest_deadline": None,
                "updated_at": now,
            },
            "$inc": {"version": 1},
        },
        return_document=ReturnDocument.AFTER,
    )
    if result is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Queue entry state changed, please retry")

    await broadcast_queue_updated(manager, str(entry["machine_id"]))
    return result


async def finish_active(db, manager: ConnectionManager, entry_id: ObjectId, user_id: ObjectId) -> dict:
    entry = await get_entry_or_404(db, entry_id)
    _require_member(entry, user_id)
    if entry["state"] not in (QueueState.ACTIVE.value, QueueState.RESTING.value):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Entry is not currently active")
    return await _start_end_of_use_grace(db, manager, entry)


async def leave_queue(db, manager: ConnectionManager, entry_id: ObjectId, user_id: ObjectId) -> dict:
    entry = await get_entry_or_404(db, entry_id)
    _require_member(entry, user_id)
    now = datetime.now(timezone.utc)

    if entry["state"] == QueueState.WAITING.value:
        remaining = [u for u in entry["user_ids"] if u != user_id]
        new_state = QueueState.WAITING.value if remaining else QueueState.REMOVED.value
        result = await db.queue_entries.find_one_and_update(
            {"_id": entry_id, "state": QueueState.WAITING.value, "version": entry["version"]},
            {
                "$set": {"user_ids": remaining, "state": new_state, "updated_at": now},
                "$inc": {"version": 1},
            },
            return_document=ReturnDocument.AFTER,
        )
        if result is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Queue entry state changed, please retry")
        await broadcast_queue_updated(manager, str(entry["machine_id"]))
        return result

    if entry["state"] == QueueState.GRACE.value and entry.get("grace_reason") == GraceReason.TURN_START.value:
        result = await db.queue_entries.find_one_and_update(
            {"_id": entry_id, "state": QueueState.GRACE.value, "version": entry["version"]},
            {"$set": {"state": QueueState.REMOVED.value, "updated_at": now}, "$inc": {"version": 1}},
            return_document=ReturnDocument.AFTER,
        )
        if result is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Queue entry state changed, please retry")
        await notify_users(
            db,
            manager,
            [str(u) for u in result["user_ids"]],
            EventType.REMOVED_FROM_QUEUE,
            {"machine_id": str(entry["machine_id"]), "queue_entry_id": str(entry_id), "reason": "left_voluntarily"},
        )
        for uid in result["user_ids"]:
            await vision_client.notify_release(str(entry["machine_id"]), str(uid))
        await release_machine_and_promote(db, manager, entry["machine_id"])
        await broadcast_queue_updated(manager, str(entry["machine_id"]))
        return result

    if entry["state"] in (QueueState.ACTIVE.value, QueueState.RESTING.value):
        return await _start_end_of_use_grace(db, manager, entry)

    if entry["state"] == QueueState.GRACE.value and entry.get("grace_reason") == GraceReason.END_OF_USE.value:
        result = await db.queue_entries.find_one_and_update(
            {"_id": entry_id, "state": QueueState.GRACE.value, "version": entry["version"]},
            {"$set": {"state": QueueState.DONE.value, "updated_at": now}, "$inc": {"version": 1}},
            return_document=ReturnDocument.AFTER,
        )
        if result is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Queue entry state changed, please retry")
        await notify_users(
            db,
            manager,
            [str(u) for u in result["user_ids"]],
            EventType.SESSION_ENDED,
            {"machine_id": str(entry["machine_id"]), "queue_entry_id": str(entry_id), "reason": "left_voluntarily"},
        )
        for uid in result["user_ids"]:
            await vision_client.notify_release(str(entry["machine_id"]), str(uid))
        await release_machine_and_promote(db, manager, entry["machine_id"])
        await broadcast_queue_updated(manager, str(entry["machine_id"]))
        return result

    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Queue entry is already finished")


async def check_in(db, manager: ConnectionManager, entry_id: ObjectId, user_id: ObjectId) -> dict:
    entry = await get_entry_or_404(db, entry_id)
    _require_member(entry, user_id)
    if entry["state"] != QueueState.GRACE.value:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Entry is not awaiting check-in")

    now = datetime.now(timezone.utc)
    set_fields: dict = {
        "state": QueueState.ACTIVE.value,
        "grace_reason": None,
        "grace_deadline": None,
        "updated_at": now,
    }
    if entry.get("grace_reason") == GraceReason.TURN_START.value:
        set_fields["active_started_at"] = now

    result = await db.queue_entries.find_one_and_update(
        {"_id": entry_id, "state": QueueState.GRACE.value, "version": entry["version"]},
        {"$set": set_fields, "$inc": {"version": 1}},
        return_document=ReturnDocument.AFTER,
    )
    if result is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Queue entry state changed, please retry")

    await notify_users(
        db,
        manager,
        [str(u) for u in result["user_ids"]],
        EventType.CHECKED_IN,
        {"machine_id": str(entry["machine_id"]), "queue_entry_id": str(entry_id), "active_started_at": result["active_started_at"].isoformat()},
    )
    await broadcast_queue_updated(manager, str(entry["machine_id"]))
    return result


async def start_rest(db, manager: ConnectionManager, entry_id: ObjectId, user_id: ObjectId) -> dict:
    entry = await get_entry_or_404(db, entry_id)
    _require_member(entry, user_id)
    if entry["state"] != QueueState.ACTIVE.value:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Entry is not currently active")

    machine = await db.machines.find_one({"_id": entry["machine_id"]})
    max_rests = (machine.get("max_rests") if machine else None) or settings.default_max_rests
    if entry.get("rest_count", 0) >= max_rests:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Maximum of {max_rests} rests already used")

    rest_seconds = (machine.get("rest_period_seconds") if machine else None) or settings.default_rest_period_seconds
    now = datetime.now(timezone.utc)
    deadline = now + timedelta(seconds=rest_seconds)

    result = await db.queue_entries.find_one_and_update(
        {"_id": entry_id, "state": QueueState.ACTIVE.value, "version": entry["version"]},
        {
            "$set": {"state": QueueState.RESTING.value, "rest_started_at": now, "rest_deadline": deadline, "updated_at": now},
            "$inc": {"version": 1, "rest_count": 1},
        },
        return_document=ReturnDocument.AFTER,
    )
    if result is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Queue entry state changed, please retry")

    await notify_users(
        db,
        manager,
        [str(u) for u in result["user_ids"]],
        EventType.REST_STARTED,
        {
            "machine_id": str(entry["machine_id"]),
            "queue_entry_id": str(entry_id),
            "rest_deadline": deadline.isoformat(),
            "rest_count": result["rest_count"],
            "max_rests": max_rests,
        },
    )
    await vision_client.notify_rest_started(str(entry["machine_id"]), str(user_id), rest_seconds)
    await broadcast_queue_updated(manager, str(entry["machine_id"]))
    return result


async def return_from_rest(db, manager: ConnectionManager, entry_id: ObjectId, user_id: ObjectId) -> dict:
    entry = await get_entry_or_404(db, entry_id)
    _require_member(entry, user_id)
    if entry["state"] != QueueState.RESTING.value:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Entry is not currently resting")

    now = datetime.now(timezone.utc)
    result = await db.queue_entries.find_one_and_update(
        {"_id": entry_id, "state": QueueState.RESTING.value, "version": entry["version"]},
        {
            "$set": {"state": QueueState.ACTIVE.value, "rest_started_at": None, "rest_deadline": None, "updated_at": now},
            "$inc": {"version": 1},
        },
        return_document=ReturnDocument.AFTER,
    )
    if result is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Queue entry state changed, please retry")

    await notify_users(
        db,
        manager,
        [str(u) for u in result["user_ids"]],
        EventType.REST_RETURNED,
        {"machine_id": str(entry["machine_id"]), "queue_entry_id": str(entry_id)},
    )
    await vision_client.notify_rest_ended(str(entry["machine_id"]), str(user_id))
    await broadcast_queue_updated(manager, str(entry["machine_id"]))
    return result


async def list_user_queue_entries(db, user_id: ObjectId) -> list[dict]:
    cursor = db.queue_entries.find(
        {"user_ids": user_id, "state": {"$in": LIVE_STATE_VALUES}}
    ).sort("joined_at", 1)
    return await cursor.to_list(length=None)
