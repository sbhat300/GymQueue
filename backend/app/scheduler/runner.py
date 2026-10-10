import asyncio
import logging
from datetime import datetime, timedelta, timezone

from pymongo import ReturnDocument

from app.config import settings
from app.models.common import EventType, GraceReason, QueueState
from app.notifications.service import broadcast_queue_updated, notify_users
from app.queue.service import release_machine_and_promote
from app.ws.manager import ConnectionManager

logger = logging.getLogger(__name__)


async def scheduler_loop(db, manager: ConnectionManager, interval_seconds: float = 2.0) -> None:
    while True:
        try:
            await _scan_turn_start_grace(db, manager)
            await _scan_rest_expiry(db, manager)
            await _scan_end_of_use_grace(db, manager)
        except Exception:
            logger.exception("Scheduler tick failed")
        await asyncio.sleep(interval_seconds)


async def _scan_turn_start_grace(db, manager: ConnectionManager) -> None:
    now = datetime.now(timezone.utc)
    cursor = db.queue_entries.find(
        {"state": QueueState.GRACE.value, "grace_reason": GraceReason.TURN_START.value, "grace_deadline": {"$lte": now}}
    )
    async for entry in cursor:
        result = await db.queue_entries.find_one_and_update(
            {
                "_id": entry["_id"],
                "state": QueueState.GRACE.value,
                "grace_reason": GraceReason.TURN_START.value,
                "version": entry["version"],
            },
            {"$set": {"state": QueueState.REMOVED.value, "updated_at": now}, "$inc": {"version": 1}},
            return_document=ReturnDocument.AFTER,
        )
        if result is None:
            continue  # lost the race to a concurrent check-in/leave

        await notify_users(
            db,
            manager,
            [str(u) for u in result["user_ids"]],
            EventType.REMOVED_FROM_QUEUE,
            {"machine_id": str(entry["machine_id"]), "queue_entry_id": str(entry["_id"]), "reason": "grace_expired"},
        )
        await broadcast_queue_updated(manager, str(entry["machine_id"]))
        await release_machine_and_promote(db, manager, entry["machine_id"])


async def _scan_rest_expiry(db, manager: ConnectionManager) -> None:
    now = datetime.now(timezone.utc)
    cursor = db.queue_entries.find({"state": QueueState.RESTING.value, "rest_deadline": {"$lte": now}})
    async for entry in cursor:
        machine = await db.machines.find_one({"_id": entry["machine_id"]})
        grace_seconds = (machine.get("grace_period_seconds") if machine else None) or settings.default_grace_period_seconds
        deadline = now + timedelta(seconds=grace_seconds)

        result = await db.queue_entries.find_one_and_update(
            {"_id": entry["_id"], "state": QueueState.RESTING.value, "version": entry["version"]},
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
            continue  # lost the race to a concurrent rest/return

        await notify_users(
            db,
            manager,
            [str(u) for u in result["user_ids"]],
            EventType.REST_EXPIRED,
            {"machine_id": str(entry["machine_id"]), "queue_entry_id": str(entry["_id"]), "grace_deadline": deadline.isoformat()},
        )
        await broadcast_queue_updated(manager, str(entry["machine_id"]))


async def _scan_end_of_use_grace(db, manager: ConnectionManager) -> None:
    now = datetime.now(timezone.utc)
    cursor = db.queue_entries.find(
        {"state": QueueState.GRACE.value, "grace_reason": GraceReason.END_OF_USE.value, "grace_deadline": {"$lte": now}}
    )
    async for entry in cursor:
        result = await db.queue_entries.find_one_and_update(
            {
                "_id": entry["_id"],
                "state": QueueState.GRACE.value,
                "grace_reason": GraceReason.END_OF_USE.value,
                "version": entry["version"],
            },
            {"$set": {"state": QueueState.DONE.value, "updated_at": now}, "$inc": {"version": 1}},
            return_document=ReturnDocument.AFTER,
        )
        if result is None:
            continue  # lost the race to a concurrent check-in/leave

        await notify_users(
            db,
            manager,
            [str(u) for u in result["user_ids"]],
            EventType.SESSION_ENDED,
            {"machine_id": str(entry["machine_id"]), "queue_entry_id": str(entry["_id"]), "reason": "grace_expired"},
        )
        await broadcast_queue_updated(manager, str(entry["machine_id"]))
        await release_machine_and_promote(db, manager, entry["machine_id"])
