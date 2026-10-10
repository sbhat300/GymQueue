"""Idempotent seed script for campuses + machines. Run with: python -m scripts.seed"""
import asyncio
from datetime import datetime, timezone

from app.db import close_db, connect_db, get_db

CAMPUSES = [
    {"name": "North Campus Rec Center", "slug": "north-campus"},
    {"name": "South Campus Fitness Center", "slug": "south-campus"},
]

MACHINES_BY_CAMPUS_SLUG = {
    "north-campus": [
        {"name": "Squat Rack 1", "category": "squat_rack"},
        {"name": "Squat Rack 2", "category": "squat_rack"},
        {"name": "Bench Press 1", "category": "bench"},
        {"name": "Bench Press 2", "category": "bench"},
        {"name": "Treadmill 1", "category": "cardio"},
        {"name": "Lat Pulldown", "category": "machine"},
    ],
    "south-campus": [
        {"name": "Squat Rack A", "category": "squat_rack"},
        {"name": "Bench Press A", "category": "bench"},
        {"name": "Leg Press", "category": "machine"},
        {"name": "Rowing Machine 1", "category": "cardio"},
        {"name": "Cable Crossover", "category": "machine"},
    ],
}


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
