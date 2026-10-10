"""Busy times and estimated wait - deliberately basic.

Busy today: every STATS_SAMPLE_INTERVAL_SECONDS the sampler counts the people in each machine's
queue (on the machine + waiting, partners counted individually). The chart is the average of
those counts for each hour of today.

Estimated wait: every turn takes TURN_MINUTES (10-15 min). A pair working in together shares
one turn. Wait = turns ahead of you x 10-15 min.
"""
import asyncio
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.config import settings
from app.models.common import QueueState
from app.queue.service import LIVE_STATE_VALUES, OWNER_STATE_VALUES
from app.vision.service import people_on_camera

logger = logging.getLogger(__name__)


def turn_seconds() -> tuple[int, int]:
    return settings.stats_turn_min_minutes * 60, settings.stats_turn_max_minutes * 60


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
        {"hour": h, "people": round(cells[h]["people"], 1) if h in cells else None,
         "samples": cells[h]["samples"] if h in cells else 0}
        for h in range(24)
    ]


# ---------------------------------------------------------------- estimated wait
def estimate_waits(entries: list[dict]) -> tuple[dict[str, list[int]], list[int], int]:
    """({waiting entry id: [min, max] seconds}, [min, max] for a new joiner, turns ahead of a new joiner)."""
    lo, hi = turn_seconds()
    turns = 1 if any(e["state"] in OWNER_STATE_VALUES for e in entries) else 0  # whoever is on it now
    waits = {}
    for e in sorted((e for e in entries if e["state"] == QueueState.WAITING.value), key=lambda e: e["joined_at"]):
        waits[str(e["_id"])] = [turns * lo, turns * hi]
        turns += 1  # one turn per entry: partners working in together share it
    return waits, [turns * lo, turns * hi], turns


async def machine_now(db, machine: dict) -> dict:
    entries = await db.queue_entries.find(
        {"machine_id": machine["_id"], "state": {"$in": LIVE_STATE_VALUES}}
    ).to_list(length=None)
    waits, join_wait, turns = estimate_waits(entries)
    lo, hi = turn_seconds()
    return {
        "machine_id": str(machine["_id"]),
        "in_use": any(e["state"] in OWNER_STATE_VALUES for e in entries),
        "queue_length": sum(e["state"] == QueueState.WAITING.value for e in entries),
        "people_in_queue": sum(len(e["user_ids"]) for e in entries),
        "people_on_camera": people_on_camera(str(machine["_id"])),
        "turns_ahead": turns,
        "estimated_wait_seconds": join_wait,       # [min, max]
        "entry_wait_seconds": waits,               # {entry id: [min, max]}
        "turn_seconds": [lo, hi],
    }
