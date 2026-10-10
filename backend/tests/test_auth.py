from bson import ObjectId

from tests.conftest import signup


async def test_signup_login_and_profile(client, db):
    res = await client.post("/auth/signup", json={"netid": "Alice", "password": "password123"})
    assert res.status_code == 200
    body = res.json()
    assert body["user"]["netid"] == "alice"  # netid normalized to lowercase
    assert body["user"]["onboarding_complete"] is False
    assert body["user"]["face_enrolled"] is False

    headers = {"Authorization": f"Bearer {body['access_token']}"}
    res = await client.patch("/users/me/profile", json={"display_name": "Alice A"}, headers=headers)
    assert res.status_code == 200
    assert res.json()["onboarding_complete"] is True

    res = await client.post("/auth/signup", json={"netid": "alice", "password": "password123"})
    assert res.status_code == 409

    res = await client.post("/auth/login", json={"netid": "alice", "password": "wrong"})
    assert res.status_code == 401

    res = await client.post("/auth/login", json={"netid": "alice", "password": "password123"})
    assert res.status_code == 200

    # regression: /auth/login's response model must carry face_enrolled through, not just
    # /users/me - this silently dropped the field before and sent enrolled users back
    # through the face scan on every login.
    await db.users.update_one({"_id": ObjectId(body["user"]["id"])}, {"$set": {"face_enrolled": True}})
    res = await client.post("/auth/login", json={"netid": "alice", "password": "password123"})
    assert res.status_code == 200
    assert res.json()["user"]["face_enrolled"] is True


async def test_me_requires_auth(client):
    res = await client.get("/users/me")
    assert res.status_code == 401

    alice = await signup(client, "bob", "Bob B")
    res = await client.get("/users/me", headers=alice["headers"])
    assert res.status_code == 200
    assert res.json()["display_name"] == "Bob B"
