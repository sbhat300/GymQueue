"""Fill in DEMO busy-times history so the chart isn't empty before real data builds up.

    python -m scripts.seed_busy_history            # 4 weeks of made-up samples for every machine
    python -m scripts.seed_busy_history --clear    # remove all made-up samples again

Samples are marked synthetic: True, and the app shows "includes sample data" while any exist.
Real samples (from the sampler + cameras) are never touched.
"""
import argparse
import asyncio
import math
import random
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.config import settings
from app.db import close_db, connect_db, get_db

OPEN_HOUR, CLOSE_HOUR = 6, 23
STEP_MINUTES = 10
CATEGORY_DEMAND = {"squat_rack": 1.0, "bench": 0.95, "cardio": 0.8, "machine": 0.65}


def demand(weekday: int, hour: float) -> float:
    """Rough share of time a popular machine is in use (0-1)."""
    bump = lambda center, width, height: height * math.exp(-((hour - center) / width) ** 2)  # noqa: E731
    if weekday < 5:  # weekdays: before-class, lunch and evening rushes
        return 0.08 + bump(7.5, 1.2, 0.5) + bump(12.5, 1.0, 0.3) + bump(18.0, 1.8, 0.85) + bump(21.0, 1.0, 0.25)
    return 0.08 + bump(13.0, 2.6, 0.65)  # weekends: one broad midday peak


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clear", action="store_true", help="delete synthetic samples and exit")
    ap.add_argument("--days", type=int, default=28)
    args = ap.parse_args()

    await connect_db()
    db = get_db()
    removed = (await db.machine_samples.delete_many({"synthetic": True})).deleted_count
    print(f"removed {removed} old synthetic samples")
    if args.clear:
        await close_db()
        return

    rng = random.Random(42)
    tz = ZoneInfo(settings.gym_timezone)
    now = datetime.now(timezone.utc)
    start = (now - timedelta(days=args.days)).astimezone(tz).replace(minute=0, second=0, microsecond=0)
    machines = await db.machines.find({"is_active": {"$ne": False}}).to_list(length=None)
    total = 0
    for m in machines:
        scale = CATEGORY_DEMAND.get(m.get("category"), 0.7) * rng.uniform(0.85, 1.1)
        docs = []
        hour_start = start
        per_hour = 60 // STEP_MINUTES
        while hour_start < now.astimezone(tz):
            if OPEN_HOUR <= hour_start.hour < CLOSE_HOUR:
                # stratified: this hour gets exactly round(p * n) busy samples, so 4 weeks of
                # history averages to a smooth curve instead of random spikes
                p = min(0.97, max(0.0, demand(hour_start.weekday(), hour_start.hour + 0.5) * scale + rng.gauss(0, 0.04)))
                busy_slots = set(rng.sample(range(per_hour), round(p * per_hour)))
                for i in range(per_hour):
                    t = hour_start + timedelta(minutes=i * STEP_MINUTES)
                    if t >= now.astimezone(tz):
                        break
                    in_use = i in busy_slots
                    queue = max(0, round((p - 0.55) * 7 * rng.random())) if in_use else 0
                    docs.append({
                        "machine_id": m["_id"], "at": t.astimezone(timezone.utc), "in_use": in_use,
                        "queue": queue, "on_camera": None, "synthetic": True,
                    })
            hour_start += timedelta(hours=1)
        if docs:
            await db.machine_samples.insert_many(docs)
            total += len(docs)
        print(f"  {m['name']}: {len(docs)} samples")
    print(f"added {total} synthetic samples over {args.days} days")
    await close_db()


if __name__ == "__main__":
    asyncio.run(main())
