from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.config import settings
from app.models.common import QueueState

_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None


def get_db() -> AsyncIOMotorDatabase:
    assert _db is not None, "Database not initialized — call connect_db() first"
    return _db


async def connect_db() -> None:
    global _client, _db
    _client = AsyncIOMotorClient(settings.mongodb_uri, tz_aware=True)
    _db = _client[settings.mongodb_db_name]
    await _create_indexes(_db)


async def close_db() -> None:
    if _client is not None:
        _client.close()


async def _create_indexes(db: AsyncIOMotorDatabase) -> None:
    await db.users.create_index("netid", unique=True)

    await db.campuses.create_index("slug", unique=True)

    await db.machines.create_index("campus_id")

    await db.queue_entries.create_index([("machine_id", 1), ("state", 1), ("joined_at", 1)])
    await db.queue_entries.create_index("user_ids")
    await db.queue_entries.create_index([("state", 1), ("grace_deadline", 1)])
    await db.queue_entries.create_index([("state", 1), ("rest_deadline", 1)])
    owner_states = [QueueState.ACTIVE.value, QueueState.RESTING.value, QueueState.GRACE.value]
    await db.queue_entries.create_index(
        "machine_id",
        unique=True,
        partialFilterExpression={"state": {"$in": owner_states}},
        name="one_owner_per_machine",
    )

    await db.join_requests.create_index([("target_id", 1), ("status", 1)])
    await db.join_requests.create_index([("queue_entry_id", 1), ("status", 1)])

    await db.notifications.create_index([("user_id", 1), ("created_at", -1)])
    await db.notifications.create_index([("user_id", 1), ("read_at", 1)])

    await db.machine_samples.create_index([("machine_id", 1), ("at", 1)])
    await db.machine_samples.create_index("at", expireAfterSeconds=90 * 24 * 3600, name="samples_ttl")
