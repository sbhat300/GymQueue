from datetime import datetime, timezone

from bson import ObjectId

from tests.conftest import signup


async def test_join_auto_promotes_when_machine_idle(client, machine):
    alice = await signup(client, "alice", "Alice")
    res = await client.post(f"/machines/{machine['machine_id']}/queue/join", headers=alice["headers"])
    assert res.status_code == 200
    body = res.json()
    assert body["state"] == "grace"
    assert body["grace_reason"] == "turn_start"


async def test_second_joiner_waits_behind_first(client, machine):
    alice = await signup(client, "alice", "Alice")
    bob = await signup(client, "bob", "Bob")

    await client.post(f"/machines/{machine['machine_id']}/queue/join", headers=alice["headers"])
    res = await client.post(f"/machines/{machine['machine_id']}/queue/join", headers=bob["headers"])
    assert res.status_code == 200
    assert res.json()["state"] == "waiting"


async def test_wrong_person_cannot_check_in(client, machine):
    alice = await signup(client, "alice", "Alice")
    bob = await signup(client, "bob", "Bob")

    res = await client.post(f"/machines/{machine['machine_id']}/queue/join", headers=alice["headers"])
    entry_id = res.json()["id"]
    await client.post(f"/machines/{machine['machine_id']}/queue/join", headers=bob["headers"])

    res = await client.post(f"/machines/{machine['machine_id']}/queue/{entry_id}/check-in", headers=bob["headers"])
    assert res.status_code == 403
    assert "not currently assigned" in res.json()["detail"]


async def test_full_lifecycle_check_in_rest_finish_leave_promotes_next(client, machine):
    alice = await signup(client, "alice", "Alice")
    bob = await signup(client, "bob", "Bob")
    mid = machine["machine_id"]

    res = await client.post(f"/machines/{mid}/queue/join", headers=alice["headers"])
    entry_id = res.json()["id"]
    await client.post(f"/machines/{mid}/queue/join", headers=bob["headers"])

    res = await client.post(f"/machines/{mid}/queue/{entry_id}/check-in", headers=alice["headers"])
    assert res.status_code == 200
    assert res.json()["state"] == "active"

    res = await client.post(f"/machines/{mid}/queue/{entry_id}/rest/start", headers=alice["headers"])
    assert res.status_code == 200
    assert res.json()["state"] == "resting"
    assert res.json()["rest_count"] == 1

    res = await client.post(f"/machines/{mid}/queue/{entry_id}/rest/return", headers=alice["headers"])
    assert res.status_code == 200
    assert res.json()["state"] == "active"

    res = await client.post(f"/machines/{mid}/queue/{entry_id}/finish", headers=alice["headers"])
    assert res.status_code == 200
    assert res.json()["state"] == "grace"
    assert res.json()["grace_reason"] == "end_of_use"

    # second leave while already in end-of-use grace is the immediate-free fast path
    res = await client.post(f"/machines/{mid}/queue/{entry_id}/leave", headers=alice["headers"])
    assert res.status_code == 200
    assert res.json()["state"] == "done"

    res = await client.get(f"/machines/{mid}/queue", headers=alice["headers"])
    entries = res.json()
    assert len(entries) == 1
    assert entries[0]["users"][0]["display_name"] == "Bob"
    assert entries[0]["state"] == "grace"
    assert entries[0]["grace_reason"] == "turn_start"


async def test_rest_cap_enforced(client, machine):
    alice = await signup(client, "alice", "Alice")
    mid = machine["machine_id"]
    res = await client.post(f"/machines/{mid}/queue/join", headers=alice["headers"])
    entry_id = res.json()["id"]
    await client.post(f"/machines/{mid}/queue/{entry_id}/check-in", headers=alice["headers"])

    for _ in range(6):
        res = await client.post(f"/machines/{mid}/queue/{entry_id}/rest/start", headers=alice["headers"])
        assert res.status_code == 200
        await client.post(f"/machines/{mid}/queue/{entry_id}/rest/return", headers=alice["headers"])

    res = await client.post(f"/machines/{mid}/queue/{entry_id}/rest/start", headers=alice["headers"])
    assert res.status_code == 409
    assert "Maximum" in res.json()["detail"]


async def test_leave_while_waiting_removes_entry(client, machine):
    alice = await signup(client, "alice", "Alice")
    bob = await signup(client, "bob", "Bob")
    mid = machine["machine_id"]

    await client.post(f"/machines/{mid}/queue/join", headers=alice["headers"])
    res = await client.post(f"/machines/{mid}/queue/join", headers=bob["headers"])
    entry_id = res.json()["id"]
    assert res.json()["state"] == "waiting"

    res = await client.post(f"/machines/{mid}/queue/{entry_id}/leave", headers=bob["headers"])
    assert res.status_code == 200
    assert res.json()["state"] == "removed"

    res = await client.get(f"/machines/{mid}/queue", headers=alice["headers"])
    assert len(res.json()) == 1


async def test_rest_period_is_capped_even_if_machine_override_is_higher(client, db, machine):
    mid = machine["machine_id"]
    await db.machines.update_one({"_id": ObjectId(mid)}, {"$set": {"rest_period_seconds": 10_000}})

    alice = await signup(client, "alice", "Alice")
    res = await client.post(f"/machines/{mid}/queue/join", headers=alice["headers"])
    entry_id = res.json()["id"]
    await client.post(f"/machines/{mid}/queue/{entry_id}/check-in", headers=alice["headers"])

    res = await client.post(f"/machines/{mid}/queue/{entry_id}/rest/start", headers=alice["headers"])
    assert res.status_code == 200
    rest_deadline = datetime.fromisoformat(res.json()["rest_deadline"])
    assert (rest_deadline - datetime.now(timezone.utc)).total_seconds() <= 300
