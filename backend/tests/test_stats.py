import time
from datetime import datetime, timedelta, timezone

import pytest_asyncio
from bson import ObjectId

from app.stats import service as stats
from app.vision import service as vision_service
from tests.conftest import signup

NOW = datetime(2026, 10, 12, 22, 30, tzinfo=timezone.utc)  # Monday 18:30 in New York


@pytest_asyncio.fixture(autouse=True)
async def clean(db):
    vision_service._last_heartbeat.clear()
    yield
    await db.machine_samples.delete_many({})


def entry(state, joined_min_ago=0, users=1):
    return {"_id": ObjectId(), "state": state, "joined_at": NOW - timedelta(minutes=joined_min_ago),
            "user_ids": [ObjectId() for _ in range(users)]}


# ---------------------------------------------------------------- estimated wait (10-15 min per turn)
def test_each_turn_ahead_adds_10_to_15_minutes():
    owner, a, b = entry("active", 20), entry("waiting", 10), entry("waiting", 5)
    waits, join, turns = stats.estimate_waits([b, owner, a])
    assert waits == {str(a["_id"]): [600, 900], str(b["_id"]): [1200, 1800]}
    assert (join, turns) == ([1800, 2700], 3)


def test_partners_share_one_turn():
    owner = entry("active", 20, users=2)    # pair working in together
    pair = entry("waiting", 10, users=2)
    waits, join, turns = stats.estimate_waits([owner, pair])
    assert waits[str(pair["_id"])] == [600, 900]
    assert turns == 2


def test_idle_machine_has_no_wait():
    assert stats.estimate_waits([]) == ({}, [0, 0], 0)


def test_next_in_line_when_nobody_on_machine():
    a = entry("waiting")  # e.g. right after the previous person left
    waits, _, _ = stats.estimate_waits([a])
    assert waits[str(a["_id"])] == [0, 0]


# ---------------------------------------------------------------- busy today
async def test_sampler_counts_people_in_queue_including_partners(client, db, machine):
    mid = machine["machine_id"]
    alice = await signup(client, "alice", "Alice")
    bob = await signup(client, "bob", "Bob")
    res = await client.post(f"/machines/{mid}/queue/join", headers=alice["headers"])
    await db.queue_entries.update_one({"_id": ObjectId(res.json()["id"])},
                                      {"$push": {"user_ids": ObjectId(bob["user"]["id"])}})  # bob works in with alice
    carol = await signup(client, "carol", "Carol")
    await client.post(f"/machines/{mid}/queue/join", headers=carol["headers"])

    await stats.sample_all(db, NOW)
    s = await db.machine_samples.find_one({"machine_id": ObjectId(mid)})
    assert s["people"] == 3


async def test_busy_today_averages_each_local_hour(db, machine):
    mid = ObjectId(machine["machine_id"])
    samples = [(NOW, 2), (NOW + timedelta(minutes=10), 4),   # 18:30, 18:40 local -> avg 3
               (NOW - timedelta(hours=2), 1),                 # 16:30 local
               (NOW - timedelta(days=1), 9)]                  # yesterday: ignored
    await db.machine_samples.insert_many([{"machine_id": mid, "at": at, "people": p} for at, p in samples])
    hours = await stats.busy_today(db, mid, now=NOW + timedelta(minutes=20))
    assert hours[18] == {"hour": 18, "people": 3.0, "samples": 2}
    assert hours[16]["people"] == 1.0
    assert hours[10] == {"hour": 10, "people": None, "samples": 0}


async def test_stale_camera_is_ignored(machine):
    vision_service._last_heartbeat[machine["machine_id"]] = (time.monotonic() - 120, 3)
    assert vision_service.people_on_camera(machine["machine_id"]) is None


# ---------------------------------------------------------------- endpoints
async def test_machine_stats_endpoint(client, machine):
    mid = machine["machine_id"]
    alice = await signup(client, "alice", "Alice")
    bob = await signup(client, "bob", "Bob")
    await client.post(f"/machines/{mid}/queue/join", headers=alice["headers"])
    res = await client.post(f"/machines/{mid}/queue/join", headers=bob["headers"])
    bob_entry = res.json()["id"]

    body = (await client.get(f"/machines/{mid}/stats", headers=bob["headers"])).json()
    assert body["in_use"] is True and body["queue_length"] == 1 and body["people_in_queue"] == 2
    assert body["entry_wait_seconds"][bob_entry] == [600, 900]
    assert body["estimated_wait_seconds"] == [1200, 1800]
    assert body["turn_seconds"] == [600, 900]
    assert len(body["busy_today"]) == 24
    assert body["includes_demo_data"] is False


async def test_campus_summary(client, machine):
    alice = await signup(client, "alice", "Alice")
    res = await client.get(f"/campuses/{machine['campus_id']}/machine-stats", headers=alice["headers"])
    [m] = res.json()
    assert m["machine_id"] == machine["machine_id"]
    assert (m["in_use"], m["queue_length"], m["estimated_wait_seconds"]) == (False, 0, [0, 0])
