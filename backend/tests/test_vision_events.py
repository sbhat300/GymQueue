import time

from app.config import settings
from tests.conftest import signup


def _event(kind: str, machine_id: str, **data) -> dict:
    return {"id": "evt-1", "type": kind, "machine_id": machine_id, "ts": time.time(), "at": "2026-01-01T00:00:00Z", **data}


async def test_user_arrived_auto_checks_in(client, machine):
    alice = await signup(client, "alice", "Alice")
    mid = machine["machine_id"]

    res = await client.post(f"/machines/{mid}/queue/join", headers=alice["headers"])
    entry = res.json()
    assert entry["state"] == "grace"

    res = await client.post(
        "/api/vision/events",
        json={"events": [_event("user_arrived", mid, user_id=alice["user"]["id"], confidence=0.9)]},
    )
    assert res.status_code == 200

    res = await client.get(f"/machines/{mid}/queue", headers=alice["headers"])
    assert res.json()[0]["state"] == "active"


async def test_user_left_starts_end_of_use_grace(client, machine):
    alice = await signup(client, "alice", "Alice")
    mid = machine["machine_id"]

    res = await client.post(f"/machines/{mid}/queue/join", headers=alice["headers"])
    entry_id = res.json()["id"]
    await client.post(f"/machines/{mid}/queue/{entry_id}/check-in", headers=alice["headers"])

    res = await client.post(
        "/api/vision/events",
        json={"events": [_event("user_left", mid, user_id=alice["user"]["id"], last_seen=time.time(), was_resting=False)]},
    )
    assert res.status_code == 200

    res = await client.get(f"/machines/{mid}/queue", headers=alice["headers"])
    updated = res.json()[0]
    assert updated["state"] == "grace"
    assert updated["grace_reason"] == "end_of_use"


async def test_rest_ended_returned_auto_resumes(client, machine):
    alice = await signup(client, "alice", "Alice")
    mid = machine["machine_id"]

    res = await client.post(f"/machines/{mid}/queue/join", headers=alice["headers"])
    entry_id = res.json()["id"]
    await client.post(f"/machines/{mid}/queue/{entry_id}/check-in", headers=alice["headers"])
    await client.post(f"/machines/{mid}/queue/{entry_id}/rest/start", headers=alice["headers"])

    res = await client.post(
        "/api/vision/events",
        json={"events": [_event("rest_ended", mid, user_id=alice["user"]["id"], reason="returned", rests_used=1)]},
    )
    assert res.status_code == 200

    res = await client.get(f"/machines/{mid}/queue", headers=alice["headers"])
    assert res.json()[0]["state"] == "active"


async def test_rest_ended_expired_is_ignored(client, machine):
    """rest_expired reaching the backend via a rest_ended(reason=expired) event must not
    auto-resume the user - that transition is the scheduler's job (_scan_rest_expiry)."""
    alice = await signup(client, "alice", "Alice")
    mid = machine["machine_id"]

    res = await client.post(f"/machines/{mid}/queue/join", headers=alice["headers"])
    entry_id = res.json()["id"]
    await client.post(f"/machines/{mid}/queue/{entry_id}/check-in", headers=alice["headers"])
    await client.post(f"/machines/{mid}/queue/{entry_id}/rest/start", headers=alice["headers"])

    res = await client.post(
        "/api/vision/events",
        json={"events": [_event("rest_ended", mid, user_id=alice["user"]["id"], reason="expired", rests_used=1)]},
    )
    assert res.status_code == 200

    res = await client.get(f"/machines/{mid}/queue", headers=alice["headers"])
    assert res.json()[0]["state"] == "resting"


async def test_stale_event_is_ignored_without_error(client, machine):
    """A user_arrived event for someone already active (e.g. a re-recognition after a
    brief occlusion) should be a harmless no-op, not an error."""
    alice = await signup(client, "alice", "Alice")
    mid = machine["machine_id"]

    res = await client.post(f"/machines/{mid}/queue/join", headers=alice["headers"])
    entry_id = res.json()["id"]
    await client.post(f"/machines/{mid}/queue/{entry_id}/check-in", headers=alice["headers"])

    res = await client.post(
        "/api/vision/events",
        json={"events": [_event("user_arrived", mid, user_id=alice["user"]["id"], confidence=0.9)]},
    )
    assert res.status_code == 200

    res = await client.get(f"/machines/{mid}/queue", headers=alice["headers"])
    assert res.json()[0]["state"] == "active"


async def test_events_require_api_key_when_configured(client, machine):
    mid = machine["machine_id"]
    settings.vision_events_api_key = "secret-key"
    try:
        res = await client.post("/api/vision/events", json={"events": [_event("heartbeat", mid)]})
        assert res.status_code == 401

        res = await client.post(
            "/api/vision/events",
            json={"events": [_event("heartbeat", mid)]},
            headers={"Authorization": "Bearer secret-key"},
        )
        assert res.status_code == 200
    finally:
        settings.vision_events_api_key = ""


async def test_unrecognised_user_id_is_ignored(client, machine):
    """An enrolled vision user_id that isn't a GymQueue ObjectId (e.g. test/CLI
    enrollments) must not 500 the whole batch."""
    mid = machine["machine_id"]
    res = await client.post(
        "/api/vision/events",
        json={"events": [_event("user_arrived", mid, user_id="me", confidence=0.9)]},
    )
    assert res.status_code == 200
