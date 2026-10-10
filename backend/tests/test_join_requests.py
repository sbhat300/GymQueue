from tests.conftest import signup


async def test_pairing_flow(client, machine):
    alice = await signup(client, "alice", "Alice")  # occupies the machine
    carol = await signup(client, "carol", "Carol")  # joins, waits
    dave = await signup(client, "dave", "Dave")  # requests to pair with carol
    mid = machine["machine_id"]

    res = await client.post(f"/machines/{mid}/queue/join", headers=alice["headers"])
    alice_entry = res.json()["id"]
    await client.post(f"/machines/{mid}/queue/{alice_entry}/check-in", headers=alice["headers"])

    res = await client.post(f"/machines/{mid}/queue/join", headers=carol["headers"])
    carol_entry = res.json()["id"]
    assert res.json()["state"] == "waiting"

    res = await client.post(f"/machines/{mid}/queue/{carol_entry}/join-requests", headers=dave["headers"])
    assert res.status_code == 200
    request_id = res.json()["id"]
    assert res.json()["status"] == "pending"

    res = await client.get("/join-requests/incoming", headers=carol["headers"])
    assert len(res.json()) == 1
    assert res.json()[0]["id"] == request_id

    res = await client.post(f"/join-requests/{request_id}/accept", headers=carol["headers"])
    assert res.status_code == 200
    assert res.json()["status"] == "accepted"

    res = await client.get(f"/machines/{mid}/queue", headers=alice["headers"])
    entries = {e["id"]: e for e in res.json()}
    paired = entries[carol_entry]
    assert {u["display_name"] for u in paired["users"]} == {"Carol", "Dave"}


async def test_can_request_and_join_an_active_entry(client, machine):
    alice = await signup(client, "alice", "Alice")
    bob = await signup(client, "bob", "Bob")
    mid = machine["machine_id"]

    res = await client.post(f"/machines/{mid}/queue/join", headers=alice["headers"])
    entry_id = res.json()["id"]
    await client.post(f"/machines/{mid}/queue/{entry_id}/check-in", headers=alice["headers"])

    res = await client.post(f"/machines/{mid}/queue/{entry_id}/join-requests", headers=bob["headers"])
    assert res.status_code == 200
    request_id = res.json()["id"]

    res = await client.post(f"/join-requests/{request_id}/accept", headers=alice["headers"])
    assert res.status_code == 200

    res = await client.get(f"/machines/{mid}/queue", headers=alice["headers"])
    entries = res.json()
    assert len(entries) == 1
    assert entries[0]["state"] == "active"
    assert {u["display_name"] for u in entries[0]["users"]} == {"Alice", "Bob"}


async def test_cannot_request_join_on_already_paired_entry(client, machine):
    alice = await signup(client, "alice", "Alice")
    bob = await signup(client, "bob", "Bob")
    carol = await signup(client, "carol", "Carol")
    mid = machine["machine_id"]

    res = await client.post(f"/machines/{mid}/queue/join", headers=alice["headers"])
    entry_id = res.json()["id"]
    res = await client.post(f"/machines/{mid}/queue/{entry_id}/join-requests", headers=bob["headers"])
    request_id = res.json()["id"]
    await client.post(f"/join-requests/{request_id}/accept", headers=alice["headers"])

    res = await client.post(f"/machines/{mid}/queue/{entry_id}/join-requests", headers=carol["headers"])
    assert res.status_code == 409


async def test_reject_join_request(client, machine):
    alice = await signup(client, "alice", "Alice")
    carol = await signup(client, "carol", "Carol")
    dave = await signup(client, "dave", "Dave")
    mid = machine["machine_id"]

    await client.post(f"/machines/{mid}/queue/join", headers=alice["headers"])
    res = await client.post(f"/machines/{mid}/queue/join", headers=carol["headers"])
    carol_entry = res.json()["id"]

    res = await client.post(f"/machines/{mid}/queue/{carol_entry}/join-requests", headers=dave["headers"])
    request_id = res.json()["id"]

    res = await client.post(f"/join-requests/{request_id}/reject", headers=carol["headers"])
    assert res.status_code == 200
    assert res.json()["status"] == "rejected"

    res = await client.get(f"/machines/{mid}/queue", headers=alice["headers"])
    entries = {e["id"]: e for e in res.json()}
    assert len(entries[carol_entry]["users"]) == 1
