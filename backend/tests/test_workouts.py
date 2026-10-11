import time

import pytest_asyncio
from bson import ObjectId

from tests.conftest import signup


@pytest_asyncio.fixture(autouse=True)
async def clean(db):
    yield
    await db.workout_entries.delete_many({})


def _event(kind: str, machine_id: str, **data) -> dict:
    return {"id": data.pop("id", "evt-1"), "type": kind, "machine_id": machine_id, "ts": time.time(),
            "at": "2026-01-01T00:00:00Z", **data}


async def _today(client, user):
    res = await client.get("/workouts/today", headers=user["headers"])
    assert res.status_code == 200
    return res.json()["entries"]


async def test_manual_sets_are_logged_for_today(client):
    alice = await signup(client, "alice", "Alice")
    res = await client.post("/workouts/today", json={"exercise": "bench_press", "reps": 8, "weight_lbs": 135},
                            headers=alice["headers"])
    assert res.status_code == 200
    [entry] = await _today(client, alice)
    assert (entry["exercise_label"], entry["reps"], entry["weight_lbs"], entry["source"]) == ("Bench press", 8, 135, "manual")


async def test_shoulder_press_cannot_be_entered_by_hand(client):
    alice = await signup(client, "alice", "Alice")
    res = await client.post("/workouts/today", json={"exercise": "shoulder_press", "reps": 10}, headers=alice["headers"])
    assert res.status_code == 400
    assert "camera" in res.json()["detail"]
    assert await _today(client, alice) == []


async def test_bad_input_rejected(client):
    alice = await signup(client, "alice", "Alice")
    for body in ({"exercise": "jumping", "reps": 5}, {"exercise": "squat", "reps": 0}, {"exercise": "squat", "reps": 501}):
        res = await client.post("/workouts/today", json=body, headers=alice["headers"])
        assert res.status_code in (400, 422), body


async def test_camera_set_is_logged_once(client, machine):
    alice = await signup(client, "alice", "Alice")
    evt = _event("set_completed", machine["machine_id"], id="set-1", user_id=alice["user"]["id"],
                 exercise="shoulder_press", reps=9, started_at=0, ended_at=30)
    for _ in range(2):  # vision may redeliver
        res = await client.post("/api/vision/events", json={"events": [evt]})
        assert res.status_code == 200
    [entry] = await _today(client, alice)
    assert (entry["exercise"], entry["reps"], entry["source"], entry["machine_name"]) == ("shoulder_press", 9, "camera", "Test Machine")


async def test_live_rep_counts_are_not_stored(client, db, machine):
    alice = await signup(client, "alice", "Alice")
    res = await client.post("/api/vision/events", json={"events": [
        _event("rep_counted", machine["machine_id"], user_id=alice["user"]["id"], exercise="shoulder_press", reps=3)]})
    assert res.status_code == 200
    assert await _today(client, alice) == []
    assert await db.notifications.count_documents({"user_id": ObjectId(alice["user"]["id"])}) == 0


async def test_unrecognised_person_sets_are_ignored(client, machine):
    alice = await signup(client, "alice", "Alice")
    res = await client.post("/api/vision/events", json={"events": [
        _event("set_completed", machine["machine_id"], user_id=None, exercise="shoulder_press", reps=9)]})
    assert res.status_code == 200
    assert await _today(client, alice) == []


async def test_delete_only_your_own_sets(client):
    alice = await signup(client, "alice", "Alice")
    bob = await signup(client, "bob", "Bob")
    entry = (await client.post("/workouts/today", json={"exercise": "squat", "reps": 5}, headers=alice["headers"])).json()
    assert (await client.delete(f"/workouts/entries/{entry['id']}", headers=bob["headers"])).status_code == 404
    assert (await client.delete(f"/workouts/entries/{entry['id']}", headers=alice["headers"])).status_code == 200
    assert await _today(client, alice) == []


async def test_workouts_are_private(client):
    alice = await signup(client, "alice", "Alice")
    bob = await signup(client, "bob", "Bob")
    await client.post("/workouts/today", json={"exercise": "squat", "reps": 5}, headers=alice["headers"])
    assert await _today(client, bob) == []


async def test_exercise_list_marks_camera_only(client):
    alice = await signup(client, "alice", "Alice")
    exercises = (await client.get("/workouts/exercises", headers=alice["headers"])).json()
    assert {"key": "shoulder_press", "label": "Shoulder press", "camera_only": True} in exercises
