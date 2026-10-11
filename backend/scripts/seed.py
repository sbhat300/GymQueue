"""Idempotent seed script for campuses + machines. Run with: python -m scripts.seed"""
import asyncio
from datetime import datetime, timezone

from app.db import close_db, connect_db, get_db

CAMPUSES = [
    {"name": "Sonny Werblin Recreation Center (Busch Campus)", "slug": "busch"},
    {"name": "College Avenue Gym (College Ave Campus)", "slug": "college-ave"},
    {"name": "Livingston Recreation Center (Livingston Campus)", "slug": "livingston"},
    {"name": "Cook/Douglass Recreation Center (Cook/Douglass Campus)", "slug": "cook-douglass"},
    {"name": "Rutgers Fitness Center (Easton Avenue)", "slug": "easton-avenue"},
]

COMMON_MACHINES = [
    {"name": "Squat Rack 1", "category": "squat_rack"},
    {"name": "Bench Press 1", "category": "bench"},
    {"name": "Shoulder Press", "category": "shoulder_press"},
    {"name": "Leg Press", "category": "machine"},
    {"name": "Lat Pulldown", "category": "machine"},
    {"name": "Cable Crossover", "category": "machine"},
    {"name": "Treadmill 1", "category": "cardio"},
]

MACHINES_BY_CAMPUS_SLUG: dict[str, list[dict]] = {campus["slug"]: COMMON_MACHINES for campus in CAMPUSES}


async def seed() -> None:
    await connect_db()
    db = get_db()
    now = datetime.now(timezone.utc)

    campus_ids: dict[str, object] = {}
    for campus in CAMPUSES:
        result = await db.campuses.update_one(
            {"slug": campus["slug"]},
            {"$setOnInsert": {**campus, "created_at": now}},
            upsert=True,
        )
        doc = await db.campuses.find_one({"slug": campus["slug"]})
        campus_ids[campus["slug"]] = doc["_id"]
        print(f"campus ready: {campus['name']} ({'created' if result.upserted_id else 'exists'})")

    for slug, machines in MACHINES_BY_CAMPUS_SLUG.items():
        campus_id = campus_ids[slug]
        for machine in machines:
            result = await db.machines.update_one(
                {"campus_id": campus_id, "name": machine["name"]},
                {
                    "$setOnInsert": {
                        "campus_id": campus_id,
                        "name": machine["name"],
                        "category": machine["category"],
                        "grace_period_seconds": None,
                        "rest_period_seconds": None,
                        "max_rests": None,
                        "is_active": True,
                        "created_at": now,
                    }
                },
                upsert=True,
            )
            print(f"  machine ready: {machine['name']} ({'created' if result.upserted_id else 'exists'})")

    await close_db()


if __name__ == "__main__":
    asyncio.run(seed())
