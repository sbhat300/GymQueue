"""Today's workout log: sets of an exercise, entered by hand or counted by a machine camera.

Shoulder press is camera-only: its sets come from the vision service's rep counter and can't be
typed in, so the log shows what was actually done on the machine.
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from bson import ObjectId
from fastapi import HTTPException, status
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.config import settings

# key -> (label, camera only)
EXERCISES: dict[str, tuple[str, bool]] = {
    "shoulder_press": ("Shoulder press", True),
    "bench_press": ("Bench press", False),
    "squat": ("Squat", False),
    "deadlift": ("Deadlift", False),
    "leg_press": ("Leg press", False),
    "lat_pulldown": ("Lat pulldown", False),
    "row": ("Row", False),
    "cable_fly": ("Cable fly", False),
    "bicep_curl": ("Bicep curl", False),
    "tricep_extension": ("Tricep extension", False),
    "lunge": ("Lunge", False),
    "pull_up": ("Pull-up", False),
    "push_up": ("Push-up", False),
}


def today(now: datetime | None = None) -> str:
    """The gym's local date, e.g. "2026-10-10"."""
    return (now or datetime.now(timezone.utc)).astimezone(ZoneInfo(settings.gym_timezone)).date().isoformat()


def entry_to_public(doc: dict) -> dict:
    label, camera_only = EXERCISES.get(doc["exercise"], (doc["exercise"], False))
    return {
        "id": str(doc["_id"]),
        "exercise": doc["exercise"],
        "exercise_label": label,
        "reps": doc["reps"],
        "weight_lbs": doc.get("weight_lbs"),
        "source": doc["source"],  # "manual" | "camera"
        "machine_name": doc.get("machine_name"),
        "created_at": doc["created_at"].isoformat(),
    }


async def list_day(db, user_id: ObjectId, day: str) -> list[dict]:
    cursor = db.workout_entries.find({"user_id": user_id, "day": day}).sort("created_at", 1)
    return [entry_to_public(d) for d in await cursor.to_list(length=None)]


async def add_manual(db, user_id: ObjectId, exercise: str, reps: int, weight_lbs: float | None) -> dict:
    if exercise not in EXERCISES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown exercise")
    label, camera_only = EXERCISES[exercise]
    if camera_only:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"{label} reps are counted by the camera at the machine and can't be entered by hand",
        )
    now = datetime.now(timezone.utc)
    doc = {"user_id": user_id, "day": today(now), "exercise": exercise, "reps": reps,
           "weight_lbs": weight_lbs, "source": "manual", "created_at": now}
    doc["_id"] = (await db.workout_entries.insert_one(doc)).inserted_id
    return entry_to_public(doc)


async def add_camera_set(db, user_id: ObjectId, machine_id: ObjectId, exercise: str, reps: int,
                         event_id: str) -> dict | None:
    """A set counted by a machine camera. Returns None if this event was already logged."""
    if exercise not in EXERCISES or reps < 1:
        return None
    machine = await db.machines.find_one({"_id": machine_id})
    now = datetime.now(timezone.utc)
    doc = {"user_id": user_id, "day": today(now), "exercise": exercise, "reps": int(reps), "weight_lbs": None,
           "source": "camera", "machine_id": machine_id, "machine_name": machine["name"] if machine else None,
           "vision_event_id": event_id, "created_at": now}
    try:
        doc["_id"] = (await db.workout_entries.insert_one(doc)).inserted_id
    except DuplicateKeyError:
        return None  # vision retried delivery
    return entry_to_public(doc)


async def update_entry(db, user_id: ObjectId, entry_id: ObjectId, reps: int, weight_lbs: float | None) -> dict:
    """Correct the reps/weight of an existing entry (manual typo or a camera miscount)."""
    doc = await db.workout_entries.find_one_and_update(
        {"_id": entry_id, "user_id": user_id},
        {"$set": {"reps": reps, "weight_lbs": weight_lbs}},
        return_document=ReturnDocument.AFTER,
    )
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workout entry not found")
    return entry_to_public(doc)


async def delete_entry(db, user_id: ObjectId, entry_id: ObjectId) -> None:
    result = await db.workout_entries.delete_one({"_id": entry_id, "user_id": user_id})
    if result.deleted_count == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workout entry not found")
