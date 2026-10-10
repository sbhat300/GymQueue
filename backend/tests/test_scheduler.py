import asyncio

from app.scheduler.runner import _scan_end_of_use_grace, _scan_rest_expiry, _scan_turn_start_grace
from app.ws.manager import ConnectionManager
from tests.conftest import signup


async def test_turn_start_grace_expiry_removes_and_promotes_next(client, db, machine):
    alice = await signup(client, "alice", "Alice")
    bob = await signup(client, "bob", "Bob")
    mid = machine["machine_id"]

    res = await client.post(f"/machines/{mid}/queue/join", headers=alice["headers"])
    assert res.json()["state"] == "grace"
    await client.post(f"/machines/{mid}/queue/join", headers=bob["headers"])

    await asyncio.sleep(2.2)  # DEFAULT_GRACE_PERIOD_SECONDS=2 in test env (conftest)
    await _scan_turn_start_grace(db, ConnectionManager())

    res = await client.get(f"/machines/{mid}/queue", headers=alice["headers"])
    entries = res.json()
    assert len(entries) == 1
    assert entries[0]["users"][0]["display_name"] == "Bob"
    assert entries[0]["state"] == "grace"
    assert entries[0]["grace_reason"] == "turn_start"


async def test_rest_expiry_moves_to_end_of_use_grace(client, db, machine):
    alice = await signup(client, "alice", "Alice")
    mid = machine["machine_id"]

    res = await client.post(f"/machines/{mid}/queue/join", headers=alice["headers"])
    entry_id = res.json()["id"]
    await client.post(f"/machines/{mid}/queue/{entry_id}/check-in", headers=alice["headers"])
    await client.post(f"/machines/{mid}/queue/{entry_id}/rest/start", headers=alice["headers"])

    await asyncio.sleep(2.2)  # DEFAULT_REST_PERIOD_SECONDS=2 in test env (conftest)
    await _scan_rest_expiry(db, ConnectionManager())

    res = await client.get(f"/machines/{mid}/queue", headers=alice["headers"])
    entries = res.json()
    assert entries[0]["state"] == "grace"
    assert entries[0]["grace_reason"] == "end_of_use"


async def test_rest_expiry_resumes_instead_when_still_on_camera(client, db, machine):
    alice = await signup(client, "alice", "Alice")
    mid = machine["machine_id"]

    res = await client.post(f"/machines/{mid}/queue/join", headers=alice["headers"])
    entry_id = res.json()["id"]
    await client.post(f"/machines/{mid}/queue/{entry_id}/check-in", headers=alice["headers"])
    await client.post(f"/machines/{mid}/queue/{entry_id}/rest/start", headers=alice["headers"])

    await client.post(
        "/api/vision/events",
        json={
            "events": [
                {
                    "id": "evt-1",
                    "type": "heartbeat",
                    "machine_id": mid,
                    "ts": 0,
                    "at": "2026-01-01T00:00:00Z",
                    "present_user_ids": [alice["user"]["id"]],
                    "users": [],
                    "camera_online": True,
                    "fps": 5.0,
                }
            ]
        },
    )

    await asyncio.sleep(2.2)  # DEFAULT_REST_PERIOD_SECONDS=2 in test env (conftest)
    await _scan_rest_expiry(db, ConnectionManager())

    res = await client.get(f"/machines/{mid}/queue", headers=alice["headers"])
    assert res.json()[0]["state"] == "active"


async def test_end_of_use_grace_expiry_frees_and_promotes_next(client, db, machine):
    alice = await signup(client, "alice", "Alice")
    bob = await signup(client, "bob", "Bob")
    mid = machine["machine_id"]

    res = await client.post(f"/machines/{mid}/queue/join", headers=alice["headers"])
    entry_id = res.json()["id"]
    await client.post(f"/machines/{mid}/queue/{entry_id}/check-in", headers=alice["headers"])
    await client.post(f"/machines/{mid}/queue/join", headers=bob["headers"])
    await client.post(f"/machines/{mid}/queue/{entry_id}/finish", headers=alice["headers"])

    await asyncio.sleep(2.2)
    await _scan_end_of_use_grace(db, ConnectionManager())

    res = await client.get(f"/machines/{mid}/queue", headers=alice["headers"])
    entries = res.json()
    assert len(entries) == 1
    assert entries[0]["users"][0]["display_name"] == "Bob"
    assert entries[0]["state"] == "grace"
