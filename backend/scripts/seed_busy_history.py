"""Fill in DEMO queue counts for today, so the busy chart isn't empty for a demo.

    python -m scripts.seed_busy_history            # made-up samples from opening time until now
    python -m scripts.seed_busy_history --clear    # remove all made-up samples again

Samples are marked synthetic: True, and the app shows "includes sample data" while any exist.
Real samples (from the sampler) are never touched.
"""
import argparse
import asyncio
import math
import random
from datetime import timedelta, timezone

from app.db import close_db, connect_db, get_db
from app.stats.service import local_now

OPEN_HOUR = 6
STEP_MINUTES = 5
CATEGORY_DEMAND = {"squat_rack": 1.0, "bench": 0.9, "cardio": 0.7, "machine": 0.6}


def people_in_queue(hour: float) -> float:
    """Typical people in a popular machine's queue: morning, lunch and evening rushes."""
    bump = lambda center, width, height: height * math.exp(-((hour - center) / width) ** 2)  # noqa: E731
    return 0.3 + bump(7.5, 1.2, 1.5) + bump(12.5, 1.0, 1.0) + bump(18.0, 1.8, 3.0)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clear", action="store_true", help="delete synthetic samples and exit")
    args = ap.parse_args()

    await connect_db()
    db = get_db()
    removed = (await db.machine_samples.delete_many({"synthetic": True})).deleted_count
    print(f"removed {removed} old synthetic samples")
    if args.clear:
        await close_db()
        return

    rng = random.Random(42)
    now = local_now()
    start = now.replace(hour=OPEN_HOUR, minute=0, second=0, microsecond=0)
    total = 0
    for m in await db.machines.find({"is_active": {"$ne": False}}).to_list(length=None):
        scale = CATEGORY_DEMAND.get(m.get("category"), 0.7) * rng.uniform(0.8, 1.1)
        docs = []
        t = start
        while t < now:
            expected = people_in_queue(t.hour + t.minute / 60) * scale
            docs.append({
                "machine_id": m["_id"], "at": t.astimezone(timezone.utc),
                "people": max(0, round(expected + rng.gauss(0, 0.5))), "synthetic": True,
            })
            t += timedelta(minutes=STEP_MINUTES)
        if docs:
            await db.machine_samples.insert_many(docs)
            total += len(docs)
    print(f"added {total} synthetic samples for today")
    await close_db()


if __name__ == "__main__":
    asyncio.run(main())
