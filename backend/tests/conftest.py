import os
from datetime import datetime, timezone

os.environ.setdefault("MONGODB_DB_NAME", "gymqueue_test")
os.environ.setdefault("DEFAULT_GRACE_PERIOD_SECONDS", "2")
os.environ.setdefault("DEFAULT_REST_PERIOD_SECONDS", "2")
os.environ.setdefault("SCHEDULER_INTERVAL_SECONDS", "0.5")
# Tests exercise the vision integration via direct calls/mocks, not a real vision
# service or its keys - keep them blank regardless of the developer's local .env.
os.environ["VISION_URL"] = ""
os.environ["VISION_API_KEY"] = ""
os.environ["VISION_EVENTS_API_KEY"] = ""

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.db import close_db, connect_db, get_db
from app.main import app

COLLECTIONS = ["users", "campuses", "machines", "queue_entries", "join_requests", "notifications"]


@pytest_asyncio.fixture
async def db():
    await connect_db()
    database = get_db()
    yield database
    for name in COLLECTIONS:
        await database[name].delete_many({})
    await close_db()


@pytest_asyncio.fixture
async def client(db):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def machine(db):
    now = datetime.now(timezone.utc)
    campus = await db.campuses.insert_one({"name": "Test Campus", "slug": "test-campus", "created_at": now})
    result = await db.machines.insert_one(
        {
            "campus_id": campus.inserted_id,
            "name": "Test Machine",
            "category": "machine",
            "grace_period_seconds": None,
            "rest_period_seconds": None,
            "max_rests": None,
            "is_active": True,
            "created_at": now,
        }
    )
    return {"campus_id": str(campus.inserted_id), "machine_id": str(result.inserted_id)}


async def signup(client: AsyncClient, netid: str, display_name: str) -> dict:
    res = await client.post("/auth/signup", json={"netid": netid, "password": "password123"})
    assert res.status_code == 200, res.text
    token = res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    res = await client.patch("/users/me/profile", json={"display_name": display_name}, headers=headers)
    assert res.status_code == 200, res.text
    return {"token": token, "headers": headers, "user": res.json()}
