"""Turns vision presence events into the same queue-service actions a user would
trigger by tapping a button, so check-in/rest-return/finish can happen automatically
once the camera recognises someone. See vision/README.md for the event contract.
"""
import logging

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException

from app.models.common import QueueState
from app.queue import service as queue_service
from app.queue.service import LIVE_STATE_VALUES
from app.vision.schemas import VisionEvent
from app.ws.manager import ConnectionManager

log = logging.getLogger(__name__)


def _try_oid(value: str) -> ObjectId | None:
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        return None


async def _find_live_entry(db, user_id: ObjectId, machine_id: ObjectId) -> dict | None:
    entry = await db.queue_entries.find_one({"user_ids": user_id, "state": {"$in": LIVE_STATE_VALUES}})
    if entry is None or entry["machine_id"] != machine_id:
        return None
    return entry


async def _on_user_arrived(db, manager: ConnectionManager, user_id: ObjectId, machine_id: ObjectId, event: VisionEvent) -> None:
    entry = await _find_live_entry(db, user_id, machine_id)
    if entry is None or entry["state"] != QueueState.GRACE.value:
        return  # not their turn yet, or already active - nothing to do
    await queue_service.check_in(db, manager, entry["_id"], user_id)


async def _on_user_left(db, manager: ConnectionManager, user_id: ObjectId, machine_id: ObjectId, event: VisionEvent) -> None:
    entry = await _find_live_entry(db, user_id, machine_id)
    if entry is None or entry["state"] not in (QueueState.ACTIVE.value, QueueState.RESTING.value):
        return
    await queue_service.finish_active(db, manager, entry["_id"], user_id)


async def _on_rest_ended(db, manager: ConnectionManager, user_id: ObjectId, machine_id: ObjectId, event: VisionEvent) -> None:
    if getattr(event, "reason", None) != "returned":
        return  # "cancelled"/"expired" are already driven by the backend's own actions/scheduler
    entry = await _find_live_entry(db, user_id, machine_id)
    if entry is None or entry["state"] != QueueState.RESTING.value:
        return
    await queue_service.return_from_rest(db, manager, entry["_id"], user_id)


_HANDLERS = {
    "user_arrived": _on_user_arrived,
    "user_left": _on_user_left,
    "rest_ended": _on_rest_ended,
}


async def handle_vision_event(db, manager: ConnectionManager, event: VisionEvent) -> None:
    handler = _HANDLERS.get(event.type)
    if handler is None:
        return  # rest_started, rest_expired, unknown_face, camera_online/offline, heartbeat: informational only

    user_id = _try_oid(getattr(event, "user_id", ""))
    machine_id = _try_oid(event.machine_id)
    if user_id is None or machine_id is None:
        log.debug("vision event %s: not a GymQueue id, ignoring", event.type)
        return

    try:
        await handler(db, manager, user_id, machine_id, event)
    except HTTPException as e:
        # The queue entry had already moved on (manual action, scheduler expiry, a race)
        # by the time the camera's signal arrived. The camera is a convenience, not the
        # source of truth, so this is expected and not an error.
        log.debug("vision event %s for %s/%s: %s", event.type, user_id, machine_id, e.detail)
