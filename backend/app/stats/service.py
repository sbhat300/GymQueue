"""Busy times and estimated wait - deliberately basic.

Busy today: every STATS_SAMPLE_INTERVAL_SECONDS the sampler counts the people in each machine's
queue (on the machine + waiting, partners counted individually). The chart is the average of
those counts for each hour of today.

Estimated wait: every turn takes TURN_MINUTES (10-15 min). A group working in together shares
one turn, but isn't free - each extra person sharing it tacks on EXTRA_MINUTES_PER_PARTNER.
Wait = sum of the (turn + extra-per-partner) duration of every turn ahead of you.
"""
import asyncio
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from bson import ObjectId
from bson.errors import InvalidId

from app.config import settings
from app.models.common import QueueState
from app.queue.schemas import resolve_users_by_id
from app.queue.service import LIVE_STATE_VALUES, OWNER_STATE_VALUES
from app.vision.service import camera_snapshot

logger = logging.getLogger(__name__)


def turn_seconds() -> tuple[int, int]:
    return settings.stats_turn_min_minutes * 60, settings.stats_turn_max_minutes * 60


def extra_seconds_per_partner() -> int:
    return settings.stats_extra_minutes_per_partner * 60


# ---------------------------------------------------------------- sampling
async def sample_all(db, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    machines = await db.machines.find({"is_active": {"$ne": False}}, {"_id": 1}).to_list(length=None)
    people = {d["_id"]: d["n"] async for d in db.queue_entries.aggregate([
        {"$match": {"state": {"$in": LIVE_STATE_VALUES}}},
        {"$group": {"_id": "$machine_id", "n": {"$sum": {"$size": "$user_ids"}}}},
    ])}
    docs = [{"machine_id": m["_id"], "at": now, "people": people.get(m["_id"], 0)} for m in machines]
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


# ---------------------------------------------------------------- busy today
def local_now(now: datetime | None = None) -> datetime:
    return (now or datetime.now(timezone.utc)).astimezone(ZoneInfo(settings.gym_timezone))


async def busy_today(db, machine_id, now: datetime | None = None) -> list[dict]:
    """24 x {hour, people (average in the queue that hour, or None), samples} for today."""
    midnight = local_now(now).replace(hour=0, minute=0, second=0, microsecond=0)
    cells = {}
    async for d in db.machine_samples.aggregate([
        {"$match": {"machine_id": machine_id, "at": {"$gte": midnight.astimezone(timezone.utc)}}},
        {"$group": {
            "_id": {"$hour": {"date": "$at", "timezone": settings.gym_timezone}},
            "people": {"$avg": "$people"},
            "samples": {"$sum": 1},
        }},
    ]):
        cells[d["_id"]] = d
    return [
        {"hour": h, "people": round(cells[h]["people"], 1) if cells.get(h, {}).get("people") is not None else None,
         "samples": cells[h]["samples"] if h in cells else 0}
        for h in range(24)
    ]


# ---------------------------------------------------------------- estimated wait
def _turn_duration(entry: dict, lo: int, hi: int, extra: int) -> tuple[int, int]:
    """A turn's own [min, max] duration: the base turn, plus `extra` for each person
    sharing it beyond the first (working in together isn't free, but a group of N
    doesn't take N full separate turns either)."""
    partners = max(0, len(entry["user_ids"]) - 1)
    return lo + partners * extra, hi + partners * extra


def estimate_waits(entries: list[dict]) -> tuple[dict[str, list[int]], list[int], int]:
    """({waiting entry id: [min, max] seconds}, [min, max] for a new joiner, turns ahead of a new joiner)."""
    lo, hi = turn_seconds()
    extra = extra_seconds_per_partner()
    owner = next((e for e in entries if e["state"] in OWNER_STATE_VALUES), None)  # whoever is on it now
    turns = 1 if owner is not None else 0
    cum_lo, cum_hi = _turn_duration(owner, lo, hi, extra) if owner is not None else (0, 0)
    waits = {}
    for e in sorted((e for e in entries if e["state"] == QueueState.WAITING.value), key=lambda e: e["joined_at"]):
        waits[str(e["_id"])] = [cum_lo, cum_hi]
        turn_lo, turn_hi = _turn_duration(e, lo, hi, extra)  # one turn per entry: partners share it
        cum_lo += turn_lo
        cum_hi += turn_hi
        turns += 1
    return waits, [cum_lo, cum_hi], turns


def _safe_oid(value: str) -> ObjectId | None:
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        return None


async def _camera_people(db, machine_id: str) -> tuple[int | None, list[dict] | None, int | None]:
    """(people_on_camera count, [{user_id, display_name}] recognized, unrecognized-face count)."""
    snap = camera_snapshot(machine_id)
    if snap is None:
        return None, None, None
    present_ids, unknown = snap
    oids = [oid for oid in (_safe_oid(i) for i in present_ids) if oid is not None]
    users_by_id = await resolve_users_by_id(db, oids)
    camera_people = [
        {"user_id": uid, "display_name": users_by_id.get(uid, {}).get("display_name") or "Unknown"}
        for uid in present_ids
    ]
    return len(camera_people) + unknown, camera_people, unknown


async def machine_now(db, machine: dict) -> dict:
    entries = await db.queue_entries.find(
        {"machine_id": machine["_id"], "state": {"$in": LIVE_STATE_VALUES}}
    ).to_list(length=None)
    waits, join_wait, turns = estimate_waits(entries)
    lo, hi = turn_seconds()
    people_on_camera, camera_people, camera_unknown_count = await _camera_people(db, str(machine["_id"]))
    return {
        "machine_id": str(machine["_id"]),
        "in_use": any(e["state"] in OWNER_STATE_VALUES for e in entries),
        "queue_length": sum(e["state"] == QueueState.WAITING.value for e in entries),
        "people_in_queue": sum(len(e["user_ids"]) for e in entries),
        "people_on_camera": people_on_camera,
        "camera_people": camera_people,              # [{user_id, display_name}] recognized on camera now; None = no live camera
        "camera_unknown_count": camera_unknown_count, # unrecognized faces present now; None = no live camera
        "turns_ahead": turns,
        "estimated_wait_seconds": join_wait,       # [min, max]
        "entry_wait_seconds": waits,               # {entry id: [min, max]}
        "turn_seconds": [lo, hi],
        "extra_seconds_per_partner": extra_seconds_per_partner(),
    }
