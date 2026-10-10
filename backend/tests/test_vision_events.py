import time

from app.config import settings
from app.vision import client as vision_client
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


async def test_heartbeat_catches_up_a_user_already_present_before_grace_started(client, machine):
    """vision only emits user_arrived once per continuous presence streak. If someone
    was already confirmed present on camera *before* their grace period started (no
    fresh arrival event will ever fire), the next heartbeat's present_user_ids must
    still catch them and check them in."""
    alice = await signup(client, "alice", "Alice")
    mid = machine["machine_id"]

    res = await client.post(f"/machines/{mid}/queue/join", headers=alice["headers"])
    entry = res.json()
    assert entry["state"] == "grace"

    res = await client.post(
        "/api/vision/events",
        json={"events": [_event("heartbeat", mid, present_user_ids=[alice["user"]["id"]], users=[], camera_online=True, fps=5.0)]},
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


async def test_rest_ended_expired_while_seen_also_resumes(client, machine):
    """vision sends rest_ended(reason=expired) specifically when the rest ran out while
    the person was still visible (as opposed to rest_expired, which fires only when
    they're absent) - that must resume them too, not just reason=returned."""
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
    assert res.json()[0]["state"] == "active"


async def test_rest_ended_cancelled_is_ignored(client, machine):
    """reason=cancelled is just vision's echo of a return_from_rest the backend already
    made (it's the response to the DELETE /rest call return_from_rest itself sends) -
    acting on it again would just be a harmless but pointless extra round trip."""
    alice = await signup(client, "alice", "Alice")
    mid = machine["machine_id"]

    res = await client.post(f"/machines/{mid}/queue/join", headers=alice["headers"])
    entry_id = res.json()["id"]
    await client.post(f"/machines/{mid}/queue/{entry_id}/check-in", headers=alice["headers"])
    await client.post(f"/machines/{mid}/queue/{entry_id}/rest/start", headers=alice["headers"])

    res = await client.post(
        "/api/vision/events",
        json={"events": [_event("rest_ended", mid, user_id=alice["user"]["id"], reason="cancelled", rests_used=1)]},
    )
    assert res.status_code == 200

    res = await client.get(f"/machines/{mid}/queue", headers=alice["headers"])
    assert res.json()[0]["state"] == "resting"


def _heartbeat(machine_id: str, present_user_ids: list) -> dict:
    return _event("heartbeat", machine_id, present_user_ids=present_user_ids, users=[], camera_online=True, fps=5.0)


async def test_pair_turn_continues_when_one_partner_still_on_camera(client, machine):
    alice = await signup(client, "alice", "Alice")
    bob = await signup(client, "bob", "Bob")
    mid = machine["machine_id"]

    res = await client.post(f"/machines/{mid}/queue/join", headers=alice["headers"])
    entry_id = res.json()["id"]
    await client.post(f"/machines/{mid}/queue/{entry_id}/check-in", headers=alice["headers"])
    res = await client.post(f"/machines/{mid}/queue/{entry_id}/join-requests", headers=bob["headers"])
    request_id = res.json()["id"]
    await client.post(f"/join-requests/{request_id}/accept", headers=alice["headers"])

    # bob is still visible on camera even though alice just left frame
    await client.post("/api/vision/events", json={"events": [_heartbeat(mid, [bob["user"]["id"]])]})
    res = await client.post(
        "/api/vision/events",
        json={"events": [_event("user_left", mid, user_id=alice["user"]["id"], last_seen=time.time(), was_resting=False)]},
    )
    assert res.status_code == 200

    res = await client.get(f"/machines/{mid}/queue", headers=alice["headers"])
    assert res.json()[0]["state"] == "active"


async def test_pair_turn_ends_when_nobody_on_camera(client, machine):
    alice = await signup(client, "alice", "Alice")
    bob = await signup(client, "bob", "Bob")
    mid = machine["machine_id"]

    res = await client.post(f"/machines/{mid}/queue/join", headers=alice["headers"])
    entry_id = res.json()["id"]
    await client.post(f"/machines/{mid}/queue/{entry_id}/check-in", headers=alice["headers"])
    res = await client.post(f"/machines/{mid}/queue/{entry_id}/join-requests", headers=bob["headers"])
    request_id = res.json()["id"]
    await client.post(f"/join-requests/{request_id}/accept", headers=alice["headers"])

    res = await client.post(
        "/api/vision/events",
        json={"events": [_event("user_left", mid, user_id=alice["user"]["id"], last_seen=time.time(), was_resting=False)]},
    )
    assert res.status_code == 200

    res = await client.get(f"/machines/{mid}/queue", headers=alice["headers"])
    updated = res.json()[0]
    assert updated["state"] == "grace"
    assert updated["grace_reason"] == "end_of_use"


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


async def test_start_rest_notifies_vision_for_every_partner(client, machine, monkeypatch):
    """A rest exempts whoever's resting from the away-timer in vision. For a pair, that
    has to cover both partners, not just whoever tapped Start rest - otherwise the
    untold partner can still get timed out mid-rest even though the rest is legitimate."""
    alice = await signup(client, "alice", "Alice")
    bob = await signup(client, "bob", "Bob")
    mid = machine["machine_id"]

    res = await client.post(f"/machines/{mid}/queue/join", headers=alice["headers"])
    entry_id = res.json()["id"]
    await client.post(f"/machines/{mid}/queue/{entry_id}/check-in", headers=alice["headers"])
    res = await client.post(f"/machines/{mid}/queue/{entry_id}/join-requests", headers=bob["headers"])
    request_id = res.json()["id"]
    await client.post(f"/join-requests/{request_id}/accept", headers=alice["headers"])

    notified = []

    async def fake_notify_rest_started(machine_id, user_id, seconds):
        notified.append(user_id)

    monkeypatch.setattr(vision_client, "notify_rest_started", fake_notify_rest_started)

    res = await client.post(f"/machines/{mid}/queue/{entry_id}/rest/start", headers=alice["headers"])
    assert res.status_code == 200
    assert set(notified) == {alice["user"]["id"], bob["user"]["id"]}


async def test_user_arrived_with_no_queue_entry_notifies_not_queued(client, machine):
    alice = await signup(client, "alice", "Alice")
    mid = machine["machine_id"]

    res = await client.post(
        "/api/vision/events",
        json={"events": [_event("user_arrived", mid, user_id=alice["user"]["id"], confidence=0.9)]},
    )
    assert res.status_code == 200

    res = await client.get("/notifications", headers=alice["headers"])
    notifs = res.json()
    assert notifs[0]["type"] == "not_your_machine"
    assert notifs[0]["payload"]["reason"] == "not_queued"


async def test_user_arrived_while_still_waiting_notifies_not_your_turn(client, machine):
    alice = await signup(client, "alice", "Alice")
    bob = await signup(client, "bob", "Bob")
    mid = machine["machine_id"]

    await client.post(f"/machines/{mid}/queue/join", headers=alice["headers"])
    await client.post(f"/machines/{mid}/queue/join", headers=bob["headers"])

    res = await client.post(
        "/api/vision/events",
        json={"events": [_event("user_arrived", mid, user_id=bob["user"]["id"], confidence=0.9)]},
    )
    assert res.status_code == 200

    res = await client.get("/notifications", headers=bob["headers"])
    notifs = res.json()
    assert notifs[0]["type"] == "not_your_machine"
    assert notifs[0]["payload"]["reason"] == "not_your_turn"


async def test_heartbeat_catchup_does_not_send_wrong_machine_notification(client, machine):
    """The wrong-person warning must only come from a fresh user_arrived, never from the
    heartbeat catch-up path - that one repeats every heartbeat and would spam the user."""
    alice = await signup(client, "alice", "Alice")
    mid = machine["machine_id"]

    res = await client.post(
        "/api/vision/events",
        json={"events": [_heartbeat(mid, [alice["user"]["id"]])]},
    )
    assert res.status_code == 200

    res = await client.get("/notifications", headers=alice["headers"])
    assert res.json() == []


async def test_unrecognised_user_id_is_ignored(client, machine):
    """An enrolled vision user_id that isn't a GymQueue ObjectId (e.g. test/CLI
    enrollments) must not 500 the whole batch."""
    mid = machine["machine_id"]
    res = await client.post(
        "/api/vision/events",
        json={"events": [_event("user_arrived", mid, user_id="me", confidence=0.9)]},
    )
    assert res.status_code == 200
