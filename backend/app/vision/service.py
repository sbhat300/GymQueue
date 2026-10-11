"""Turns vision presence events into the same queue-service actions a user would
trigger by tapping a button, so check-in/rest-return/finish can happen automatically
once the camera recognises someone. See vision/README.md for the event contract.
"""
import logging
import time
from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException

from app.models.common import EventType, QueueState
from app.notifications.service import notify_users, send_live
from app.workouts import service as workouts
from app.queue import service as queue_service
from app.queue.service import LIVE_STATE_VALUES
from app.vision.schemas import VisionEvent
from app.ws.manager import ConnectionManager

log = logging.getLogger(__name__)

CAMERA_STALE_SECONDS = 30
SEEN_THRESHOLD_S = 0.5  # just enough to absorb a single dropped frame, not vision's steadier 2.0s "present" cutoff
# machine_id -> (monotonic time of last heartbeat, present user ids, unknown-face count,
#                per-user snapshot by id: seconds_unseen/leaves_at/resting/...)
_last_heartbeat: dict[str, tuple[float, set[str], int, dict[str, dict]]] = {}


def _fresh_heartbeat(machine_id: str) -> tuple[set[str], int, dict[str, dict]] | None:
    seen = _last_heartbeat.get(machine_id)
    if seen is None or time.monotonic() - seen[0] > CAMERA_STALE_SECONDS:
        return None
    return seen[1], seen[2], seen[3]


def people_on_camera(machine_id: str) -> int | None:
    """How many people a machine's camera sees right now (busy times); None if no live camera."""
    hb = _fresh_heartbeat(machine_id)
    return None if hb is None else len(hb[0]) + hb[1]


def any_member_present(machine_id: str, user_ids: list) -> bool:
    """Is any of these GymQueue user ids currently visible on this machine's camera?

    Used so a pair sharing one queue entry is only treated as "gone" when *everyone*
    in the pair is gone, and so a rest that ran out while someone's still standing
    right there resumes instead of ending their turn.
    """
    hb = _fresh_heartbeat(machine_id)
    if hb is None:
        return False
    present_ids = hb[0]
    return any(str(uid) in present_ids for uid in user_ids)


def leaves_at_if_off_camera(machine_id: str, user_id: str) -> str | None:
    """If this user is tracked on this machine's camera and currently NOT visible, the
    ISO deadline their turn ends at if they don't come back - for a live countdown in
    the app. None if they're on camera, untracked, resting (absence doesn't count), or
    the camera feed is stale.
    """
    hb = _fresh_heartbeat(machine_id)
    if hb is None:
        return None
    snap = hb[2].get(user_id)
    if snap is None or snap["seconds_unseen"] < SEEN_THRESHOLD_S or snap["resting"]:
        return None
    return datetime.fromtimestamp(snap["leaves_at"], tz=timezone.utc).isoformat()


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


async def _notify_wrong_machine(db, manager: ConnectionManager, user_id: ObjectId, machine_id: ObjectId, reason: str) -> None:
    machine = await db.machines.find_one({"_id": machine_id})
    await notify_users(
        db,
        manager,
        [str(user_id)],
        EventType.NOT_YOUR_MACHINE,
        {"machine_id": str(machine_id), "machine_name": machine["name"] if machine else None, "reason": reason},
    )


async def _on_user_arrived(db, manager: ConnectionManager, user_id: ObjectId, machine_id: ObjectId, event: VisionEvent) -> None:
    entry = await _find_live_entry(db, user_id, machine_id)
    if entry is not None and entry["state"] == QueueState.GRACE.value:
        await queue_service.check_in(db, manager, entry["_id"], user_id)
        return
    if event.type != "user_arrived":
        return  # heartbeat catch-up only checks people in - warning here would repeat every heartbeat
    if entry is None:
        await _notify_wrong_machine(db, manager, user_id, machine_id, "not_queued")
    elif entry["state"] == QueueState.WAITING.value:
        await _notify_wrong_machine(db, manager, user_id, machine_id, "not_your_turn")
    # ACTIVE/RESTING here just means a re-recognition of the machine's current owner - fine


async def _on_user_left(db, manager: ConnectionManager, user_id: ObjectId, machine_id: ObjectId, event: VisionEvent) -> None:
    entry = await _find_live_entry(db, user_id, machine_id)
    if entry is None or entry["state"] not in (QueueState.ACTIVE.value, QueueState.RESTING.value):
        return
    if len(entry["user_ids"]) > 1:
        partners = [u for u in entry["user_ids"] if u != user_id]
        if any_member_present(str(machine_id), partners):
            return  # a partner is still at the machine - the pair's turn continues
    await queue_service.finish_active(db, manager, entry["_id"], user_id)


async def _on_rest_ended(db, manager: ConnectionManager, user_id: ObjectId, machine_id: ObjectId, event: VisionEvent) -> None:
    reason = getattr(event, "reason", None)
    if reason not in ("returned", "expired"):
        return  # "cancelled" is just an echo of a return_from_rest the backend already made
    entry = await _find_live_entry(db, user_id, machine_id)
    if entry is None or entry["state"] != QueueState.RESTING.value:
        return
    await queue_service.return_from_rest(db, manager, entry["_id"], user_id)


async def _on_rep_counted(db, manager: ConnectionManager, user_id: ObjectId, machine_id: ObjectId, event: VisionEvent) -> None:
    """Live rep count for the person on the machine (not stored - the finished set is)."""
    machine = await db.machines.find_one({"_id": machine_id})
    await send_live(manager, [str(user_id)], EventType.REP_COUNTED, {
        "machine_id": str(machine_id),
        "machine_name": machine["name"] if machine else None,
        "exercise": getattr(event, "exercise", None),
        "reps": getattr(event, "reps", 0),
    })


async def _on_set_completed(db, manager: ConnectionManager, user_id: ObjectId, machine_id: ObjectId, event: VisionEvent) -> None:
    """A set the camera counted goes into the user's workout for today."""
    entry = await workouts.add_camera_set(
        db, user_id, machine_id, getattr(event, "exercise", ""), int(getattr(event, "reps", 0) or 0), event.id
    )
    if entry is not None:
        await send_live(manager, [str(user_id)], EventType.WORKOUT_LOGGED, entry)


_HANDLERS = {
    "user_arrived": _on_user_arrived,
    "user_left": _on_user_left,
    "rest_ended": _on_rest_ended,
    "rep_counted": _on_rep_counted,
    "set_completed": _on_set_completed,
}


async def _catch_up_present_users(db, manager: ConnectionManager, event: VisionEvent) -> None:
    """Vision only emits user_arrived once per continuous presence streak, so someone
    already confirmed present *before* their grace period started (e.g. they were
    standing at the machine while still queued) never generates a fresh arrival event.
    Heartbeats repeat every HEARTBEAT_S regardless, so use them to catch that case too.
    """
    machine_id = _try_oid(event.machine_id)
    if machine_id is None:
        return
    for uid in getattr(event, "present_user_ids", None) or []:
        user_id = _try_oid(uid)
        if user_id is None:
            continue
        try:
            await _on_user_arrived(db, manager, user_id, machine_id, event)
        except HTTPException as e:
            log.debug("heartbeat catch-up for %s/%s: %s", user_id, machine_id, e.detail)


async def handle_vision_event(db, manager: ConnectionManager, event: VisionEvent) -> None:
    if event.type == "heartbeat":
        present_ids = {str(u) for u in (getattr(event, "present_user_ids", None) or [])}
        unknown = int(getattr(event, "unknown_faces", 0) or 0)
        users_by_id = {str(u["user_id"]): u for u in (getattr(event, "users", None) or [])}
        _last_heartbeat[event.machine_id] = (time.monotonic(), present_ids, unknown, users_by_id)
        await _catch_up_present_users(db, manager, event)
        return  # heartbeat itself has no _HANDLERS entry - nothing else to dispatch

    handler = _HANDLERS.get(event.type)
    if handler is None:
        return  # rest_started, rest_expired, unknown_face, camera_online/offline: informational only

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
