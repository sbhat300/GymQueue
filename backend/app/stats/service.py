"""Busy times and estimated wait.

Busy times: every STATS_SAMPLE_INTERVAL_SECONDS the sampler records, per machine, whether it is
in use (someone holds it in the queue, or its camera sees anyone - walk-ins who never opened the
app included) and how many people are waiting. Stats average those by local weekday + hour.

Estimated wait: built from how long people actually hold this machine (median of recent
finished sessions, or a per-category default until there are enough), plus how far the
current user is into their session.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from statistics import median
from zoneinfo import ZoneInfo

from bson import ObjectId

from app.config import settings
from app.models.common import GraceReason, QueueState
from app.queue.service import OWNER_STATE_VALUES
from app.vision.service import people_on_camera

logger = logging.getLogger(__name__)

DEFAULT_SESSION_SECONDS = {"squat_rack": 900, "bench": 720, "cardio": 1200, "machine": 600}
FALLBACK_SESSION_SECONDS = 600
MIN_SESSIONS_FOR_HISTORY = 3
RECENT_SESSIONS = 50
HANDOFF_SECONDS = 45  # next person walking over and getting checked in


# ---------------------------------------------------------------- sampling
async def sample_all(db, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    machines = await db.machines.find({"is_active": {"$ne": False}}, {"_id": 1}).to_list(length=None)
    held = {e["machine_id"] for e in await db.queue_entries.find(
        {"state": {"$in": OWNER_STATE_VALUES}}, {"machine_id": 1}).to_list(length=None)}
    waiting = {d["_id"]: d["n"] async for d in db.queue_entries.aggregate([
        {"$match": {"state": QueueState.WAITING.value}},
        {"$group": {"_id": "$machine_id", "n": {"$sum": 1}}},
    ])}
    docs = []
    for m in machines:
        on_camera = people_on_camera(str(m["_id"]))
        docs.append({
            "machine_id": m["_id"],
            "at": now,
            "in_use": m["_id"] in held or bool(on_camera),
            "queue": waiting.get(m["_id"], 0),
            "on_camera": on_camera,
        })
    if docs:
        await db.machine_samples.insert_many(docs)
    return len(docs)


async def sampler_loop(db, interval_seconds: float) -> None:
    while True:
        try:
            await sample_all(db)
        except Exception:
            logger.exception("Busy-times sample failed")
        await asyncio.sleep(interval_seconds)


# ---------------------------------------------------------------- busy times
def local_now(now: datetime | None = None) -> datetime:
    return (now or datetime.now(timezone.utc)).astimezone(ZoneInfo(settings.gym_timezone))


async def busy_times(db, machine_id: ObjectId, now: datetime | None = None) -> list[list[dict]]:
    """7 days (Mon..Sun) x 24 hours of {hour, busy (0-1 share of time in use), queue, samples}."""
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=settings.stats_history_days)
    tz = settings.gym_timezone
    cells = {}
    async for d in db.machine_samples.aggregate([
        {"$match": {"machine_id": machine_id, "at": {"$gte": since}}},
        {"$group": {
            "_id": {"dow": {"$isoDayOfWeek": {"date": "$at", "timezone": tz}},
                    "hour": {"$hour": {"date": "$at", "timezone": tz}}},
            "busy": {"$avg": {"$cond": ["$in_use", 1, 0]}},
            "queue": {"$avg": "$queue"},
            "samples": {"$sum": 1},
        }},
    ]):
        cells[(d["_id"]["dow"] - 1, d["_id"]["hour"])] = d
    grid = []
    for day in range(7):
        row = []
        for hour in range(24):
            d = cells.get((day, hour))
            row.append({
                "hour": hour,
                "busy": round(d["busy"], 3) if d else None,
                "queue": round(d["queue"], 1) if d else None,
                "samples": d["samples"] if d else 0,
            })
        grid.append(row)
    return grid


# ---------------------------------------------------------------- estimated wait
async def typical_session(db, machine: dict) -> tuple[int, str, int]:
    """(seconds, "history" | "default", sessions counted) - how long people hold this machine."""
    docs = await db.queue_entries.find(
        {"machine_id": machine["_id"], "state": QueueState.DONE.value, "active_started_at": {"$ne": None}},
        {"active_started_at": 1, "updated_at": 1},
    ).sort("updated_at", -1).limit(RECENT_SESSIONS).to_list(length=None)
    durations = [
        min(max((d["updated_at"] - d["active_started_at"]).total_seconds(), 60), 3 * 3600)
        for d in docs if d.get("updated_at") and d.get("active_started_at")
    ]
    if len(durations) >= MIN_SESSIONS_FOR_HISTORY:
        return int(median(durations)), "history", len(durations)
    return DEFAULT_SESSION_SECONDS.get(machine.get("category"), FALLBACK_SESSION_SECONDS), "default", len(durations)


def _seconds_until(deadline: datetime | None, now: datetime) -> float:
    return max(0.0, (deadline - now).total_seconds()) if deadline else 0.0


def owner_remaining_seconds(owner: dict, typical: int, now: datetime) -> float:
    """How long until the current owner frees the machine."""
    state, reason = owner["state"], owner.get("grace_reason")
    if state == QueueState.GRACE.value and reason == GraceReason.END_OF_USE.value:
        return _seconds_until(owner.get("grace_deadline"), now)  # walked off / finished; grace runs out
    if state == QueueState.GRACE.value:  # their turn just started, not checked in yet
        return min(HANDOFF_SECONDS, _seconds_until(owner.get("grace_deadline"), now)) + typical
    elapsed = (now - owner["active_started_at"]).total_seconds() if owner.get("active_started_at") else 0
    # running past the usual length: assume they're wrapping up, not that the wait is zero
    remaining = max(typical - elapsed, min(120, typical * 0.2))
    if state == QueueState.RESTING.value:
        remaining = max(remaining, _seconds_until(owner.get("rest_deadline"), now))
    return remaining


def estimate_waits(entries: list[dict], typical: int, now: datetime) -> tuple[dict[str, int], int]:
    """({waiting entry id: seconds until their turn}, seconds until a new joiner's turn)."""
    owner = next((e for e in entries if e["state"] in OWNER_STATE_VALUES), None)
    t = owner_remaining_seconds(owner, typical, now) if owner else 0.0
    waits = {}
    for e in sorted((e for e in entries if e["state"] == QueueState.WAITING.value), key=lambda e: e["joined_at"]):
        waits[str(e["_id"])] = int(t)
        t += HANDOFF_SECONDS + typical
    return waits, int(t)


async def machine_now(db, machine: dict, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    entries = await db.queue_entries.find(
        {"machine_id": machine["_id"], "state": {"$in": [QueueState.WAITING.value, *OWNER_STATE_VALUES]}}
    ).to_list(length=None)
    typical, source, counted = await typical_session(db, machine)
    waits, join_wait = estimate_waits(entries, typical, now)
    on_camera = people_on_camera(str(machine["_id"]))
    held = any(e["state"] in OWNER_STATE_VALUES for e in entries)
    return {
        "machine_id": str(machine["_id"]),
        "in_use": held or bool(on_camera),
        "queue_length": sum(e["state"] == QueueState.WAITING.value for e in entries),
        "people_on_camera": on_camera,
        "estimated_wait_seconds": join_wait,
        "entry_wait_seconds": waits,
        "typical_session_seconds": typical,
        "typical_session_source": source,
        "sessions_counted": counted,
    }
