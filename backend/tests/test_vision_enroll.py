import pytest

from app.vision import enroll_client
from tests.conftest import signup


async def test_enroll_client_raises_503_when_vision_unconfigured():
    # settings.vision_url defaults to "" in the test environment (no .env loaded)
    with pytest.raises(Exception) as exc_info:
        await enroll_client.start("some-user-id", "Some Name")
    assert getattr(exc_info.value, "status_code", None) == 503


async def test_enroll_start_requires_auth(client):
    res = await client.post("/vision/enroll/start")
    assert res.status_code == 401


async def test_enroll_start_uses_authenticated_user_id(client, monkeypatch):
    alice = await signup(client, "alice", "Alice")
    captured = {}

    async def fake_start(user_id: str, label: str) -> dict:
        captured["user_id"] = user_id
        captured["label"] = label
        return {"session_id": "sess-1", "user_id": user_id, "step": "center", "instruction": "Look straight"}

    monkeypatch.setattr(enroll_client, "start", fake_start)

    res = await client.post("/vision/enroll/start", headers=alice["headers"])
    assert res.status_code == 200
    assert captured["user_id"] == alice["user"]["id"]
    assert captured["label"] == "Alice"
    assert res.json()["session_id"] == "sess-1"


async def test_enroll_frame_forwarded_to_vision(client, monkeypatch):
    alice = await signup(client, "alice", "Alice")

    async def fake_start(user_id: str, label: str) -> dict:
        return {"session_id": "sess-2", "user_id": user_id, "step": "center", "instruction": "Look straight"}

    captured = {}

    async def fake_frame(session_id: str, image_data_url: str) -> dict:
        captured["session_id"] = session_id
        captured["image"] = image_data_url
        return {"session_id": session_id, "step": "left", "accepted": True, "message": "Got it", "progress": 0.2, "done": False}

    monkeypatch.setattr(enroll_client, "start", fake_start)
    monkeypatch.setattr(enroll_client, "send_frame", fake_frame)

    await client.post("/vision/enroll/start", headers=alice["headers"])
    res = await client.post(
        "/vision/enroll/sess-2/frame", json={"image": "data:image/jpeg;base64,abc"}, headers=alice["headers"]
    )
    assert res.status_code == 200
    assert captured == {"session_id": "sess-2", "image": "data:image/jpeg;base64,abc"}
    assert res.json()["accepted"] is True


async def test_cannot_post_frames_into_another_users_session(client, monkeypatch):
    alice = await signup(client, "alice", "Alice")
    bob = await signup(client, "bob", "Bob")

    async def fake_start(user_id: str, label: str) -> dict:
        return {"session_id": "sess-3", "user_id": user_id, "step": "center", "instruction": "Look straight"}

    monkeypatch.setattr(enroll_client, "start", fake_start)
    await client.post("/vision/enroll/start", headers=alice["headers"])

    async def fail_frame(*args, **kwargs):
        raise AssertionError("vision should never be called for a session bob doesn't own")

    monkeypatch.setattr(enroll_client, "send_frame", fail_frame)

    res = await client.post(
        "/vision/enroll/sess-3/frame", json={"image": "data:image/jpeg;base64,abc"}, headers=bob["headers"]
    )
    assert res.status_code == 404


async def test_finish_releases_session_ownership(client, monkeypatch):
    alice = await signup(client, "alice", "Alice")

    async def fake_start(user_id: str, label: str) -> dict:
        return {"session_id": "sess-4", "user_id": user_id, "step": "center", "instruction": "Look straight"}

    async def fake_finish(session_id: str) -> dict:
        return {"user_id": "irrelevant", "poses": ["center"], "stored": True}

    monkeypatch.setattr(enroll_client, "start", fake_start)
    monkeypatch.setattr(enroll_client, "finish", fake_finish)

    await client.post("/vision/enroll/start", headers=alice["headers"])
    res = await client.post("/vision/enroll/sess-4/finish", headers=alice["headers"])
    assert res.status_code == 200
    assert res.json()["stored"] is True

    # ownership record is gone; a stale finish/frame against sess-4 now falls through
    # to vision itself rather than being blocked at the ownership check
    async def fake_frame_after_finish(session_id: str, image_data_url: str) -> dict:
        return {"session_id": session_id, "step": None, "done": True}

    monkeypatch.setattr(enroll_client, "send_frame", fake_frame_after_finish)
    res = await client.post(
        "/vision/enroll/sess-4/frame", json={"image": "x"}, headers=alice["headers"]
    )
    assert res.status_code == 200


async def test_enroll_errors_from_vision_propagate(client, monkeypatch):
    alice = await signup(client, "alice", "Alice")

    async def fake_start(user_id: str, label: str) -> dict:
        return {"session_id": "sess-5", "user_id": user_id, "step": "center", "instruction": "Look straight"}

    from fastapi import HTTPException

    async def fake_finish(session_id: str) -> dict:
        raise HTTPException(409, "This face is already registered to another account")

    monkeypatch.setattr(enroll_client, "start", fake_start)
    monkeypatch.setattr(enroll_client, "finish", fake_finish)

    await client.post("/vision/enroll/start", headers=alice["headers"])
    res = await client.post("/vision/enroll/sess-5/finish", headers=alice["headers"])
    assert res.status_code == 409
    assert "already registered" in res.json()["detail"]
