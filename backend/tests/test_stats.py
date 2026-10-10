import time
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from bson import ObjectId

from app.config import settings
from app.stats import service as stats
from app.stats.service import HANDOFF_SECONDS
from app.vision import service as vision_service
from tests.conftest import signup

NOW = datetime(2026, 10, 12, 22, 30, tzinfo=timezone.utc)  # Monday 18:30 in New York


@pytest_asyncio.fixture(autouse=True)
async def clean(db):
    vision_service._last_heartbeat.clear()
    yield
    await db.machine_samples.delete_many({})


def entry(state, joined_min_ago=0, **kw):
    return {"_id": ObjectId(), "state": state, "joined_at": NOW - timedelta(minutes=joined_min_ago), **kw}


# ---------------------------------------------------------------- estimated wait
def test_waits_stack_behind_current_user():
    owner = entry("active", 20, active_started_at=NOW - timedelta(minutes=5))
    a, b = entry("waiting", 10), entry("waiting", 5)
    waits, join = stats.estimate_waits([b, owner, a], typical=600, now=NOW)
    assert waits == {str(a["_id"]): 300, str(b["_id"]): 300 + HANDOFF_SECONDS + 600}
    assert join == 300 + 2 * (HANDOFF_SECONDS + 600)


def test_idle_machine_has_no_wait():
    assert stats.estimate_waits([], typical=600, now=NOW) == ({}, 0)


@pytest.mark.parametrize("owner, expected", [
    # ran past the usual length: assume wrapping up, never "0 min"
    (entry("active", active_started_at=NOW - timedelta(minutes=15)), 120),
    # walked off: only the end-of-use grace is left
    (entry("grace", grace_reason="end_of_use", grace_deadline=NOW + timedelta(seconds=50)), 50),
    # their turn just started: walk over + a full session
    (entry("grace", grace_reason="turn_start", grace_deadline=NOW + timedelta(seconds=100)), HANDOFF_SECONDS + 600),
    # resting longer than their session would otherwise last
    (entry("resting", active_started_at=NOW - timedelta(minutes=9), rest_deadline=NOW + timedelta(minutes=4)), 240),
])
def test_owner_remaining(owner, expected):
    assert stats.owner_remaining_seconds(owner, typical=600, now=NOW) == expected


async def test_typical_session_learns_from_history(db, machine):
    m = await db.machines.find_one({"_id": ObjectId(machine["machine_id"])})
    assert await stats.typical_session(db, m) == (600, "default", 0)  # category "machine"
    for minutes in (8, 10, 30):
        start = NOW - timedelta(hours=1)
        await db.queue_entries.insert_one({"machine_id": m["_id"], "state": "done", "user_ids": [],
                                           "active_started_at": start, "updated_at": start + timedelta(minutes=minutes)})
    assert await stats.typical_session(db, m) == (600, "history", 3)  # median 10 min


# ---------------------------------------------------------------- sampling + busy times
async def test_sampler_counts_queue_and_camera(client, db, machine, monkeypatch):
    mid = machine["machine_id"]
    alice = await signup(client, "alice", "Alice")
    bob = await signup(client, "bob", "Bob")
    await client.post(f"/machines/{mid}/queue/join", headers=alice["headers"])
    await client.post(f"/machines/{mid}/queue/join", headers=bob["headers"])
    monkeypatch.setattr(settings, "vision_events_api_key", "k")
    res = await client.post("/api/vision/events", headers={"Authorization": "Bearer k"}, json={"events": [
        {"id": "e1", "type": "heartbeat", "machine_id": mid, "ts": 0, "at": "", "present_user_ids": [], "unknown_faces": 2}]})
    assert res.status_code == 200, res.text

    assert await stats.sample_all(db, NOW) == 1
    s = await db.machine_samples.find_one({"machine_id": ObjectId(mid)})
    assert (s["in_use"], s["queue"], s["on_camera"]) == (True, 1, 2)


async def test_walk_ins_without_the_app_count_as_busy(db, machine):
    vision_service._last_heartbeat[machine["machine_id"]] = (time.monotonic(), 1)
    await stats.sample_all(db, NOW)
    s = await db.machine_samples.find_one({"machine_id": ObjectId(machine["machine_id"])})
    assert s["in_use"] is True


async def test_stale_camera_is_ignored(db, machine):
    vision_service._last_heartbeat[machine["machine_id"]] = (time.monotonic() - 120, 3)
    assert vision_service.people_on_camera(machine["machine_id"]) is None


async def test_busy_times_grouped_by_local_weekday_and_hour(db, machine):
    mid = ObjectId(machine["machine_id"])
    samples = [(NOW, True, 2), (NOW + timedelta(minutes=10), False, 0),  # Mon 18:xx local
               (NOW - timedelta(days=7), True, 0),                         # last Monday 18:30
               (NOW + timedelta(hours=10), True, 0)]                       # Tue 04:30 local
    await db.machine_samples.insert_many([{"machine_id": mid, "at": at, "in_use": u, "queue": q} for at, u, q in samples])
    grid = await stats.busy_times(db, mid, now=NOW + timedelta(hours=11))
    assert grid[0][18] == {"hour": 18, "busy": 0.667, "queue": 0.7, "samples": 3}
    assert grid[1][4]["samples"] == 1
    assert grid[0][17] == {"hour": 17, "busy": None, "queue": None, "samples": 0}


# ---------------------------------------------------------------- endpoints
async def test_machine_stats_endpoint(client, machine):
    mid = machine["machine_id"]
    alice = await signup(client, "alice", "Alice")
    bob = await signup(client, "bob", "Bob")
    await client.post(f"/machines/{mid}/queue/join", headers=alice["headers"])
    res = await client.post(f"/machines/{mid}/queue/join", headers=bob["headers"])
    bob_entry = res.json()["id"]

    body = (await client.get(f"/machines/{mid}/stats", headers=bob["headers"])).json()
    assert body["in_use"] is True and body["queue_length"] == 1
    # alice was just called (tests use a 2 s grace): her check-in + one 10-minute session
    assert 600 <= body["entry_wait_seconds"][bob_entry] <= 603
    assert body["estimated_wait_seconds"] > body["entry_wait_seconds"][bob_entry]
    assert len(body["busy_times"]) == 7 and len(body["busy_times"][0]) == 24
    assert body["includes_demo_data"] is False
    assert 0 <= body["local_weekday"] <= 6 and 0 <= body["local_hour"] <= 23


async def test_campus_summary(client, machine):
    alice = await signup(client, "alice", "Alice")
    res = await client.get(f"/campuses/{machine['campus_id']}/machine-stats", headers=alice["headers"])
    assert res.status_code == 200
    [m] = res.json()
    assert m["machine_id"] == machine["machine_id"]
    assert (m["in_use"], m["queue_length"], m["estimated_wait_seconds"]) == (False, 0, 0)
