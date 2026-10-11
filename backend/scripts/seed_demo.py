"""Seed a few fake people already queued/active/resting on real machines, for demos.

    python -m scripts.seed_demo            # add demo people (run `scripts.seed` first)
    python -m scripts.seed_demo --reset    # clear existing demo people, then reseed
    python -m scripts.seed_demo --clear    # remove all demo people + their queue entries

Builds state through the real app.queue.service functions (join/check-in/rest), so every
queue entry respects the same invariants (grace deadlines, one-owner-per-machine, etc.) a
real user action would. Demo users are tagged is_demo: True, and that tag is stamped onto
their queue entries too, so --clear can wipe them without touching any real data.

Log in as yourself and open a seeded machine to see them in the queue, or log in as one of
the demo accounts (netid below, password DEMO_PASSWORD) to see the app from their side.
"""
import argparse
import asyncio
from datetime import datetime, timedelta, timezone

from app.auth.security import hash_password
from app.db import close_db, connect_db, get_db
from app.queue import service
from app.ws.manager import manager

DEMO_PASSWORD = "demo-pass-123"

DEMO_PEOPLE = [
    ("demo_alex", "Alex Rivera"),
    ("demo_jordan", "Jordan Lee"),
    ("demo_sam", "Sam Patel"),
    ("demo_taylor", "Taylor Kim"),
    ("demo_morgan", "Morgan Davis"),
    ("demo_casey", "Casey Nguyen"),
    ("demo_riley", "Riley Chen"),
    ("demo_jamie", "Jamie Brooks"),
]
DEMO_NETIDS = {netid for netid, _ in DEMO_PEOPLE}
DISPLAY_NAME_BY_NETID = dict(DEMO_PEOPLE)

# For each machine (filled in with the first N machines found): who joins, in join order.
# The first "active"/"resting"/"pending" person on an idle machine is the one auto-promoted
# to grace by join_queue, so it must come before any "waiting" person on the same machine.
SCENARIOS = [
    [("demo_alex", "active"), ("demo_jordan", "waiting"), ("demo_sam", "waiting")],
    [("demo_taylor", "resting"), ("demo_morgan", "waiting")],
    [("demo_casey", "active")],
    [("demo_riley", "pending"), ("demo_jamie", "waiting")],
]

ROLE_LABEL = {
    "active": "active (checked in)",
    "resting": "resting",
    "pending": "awaiting check-in (it's their turn)",
    "waiting": "waiting in queue",
}


async def clear_demo_data(db) -> None:
    demo_user_ids = [u["_id"] for u in await db.users.find({"is_demo": True}).to_list(length=None)]
    if not demo_user_ids:
        print("no demo data found")
        return
    entries = (await db.queue_entries.delete_many({"user_ids": {"$in": demo_user_ids}})).deleted_count
    notifs = (await db.notifications.delete_many({"user_id": {"$in": demo_user_ids}})).deleted_count
    users = (await db.users.delete_many({"_id": {"$in": demo_user_ids}})).deleted_count
    print(f"removed {users} demo users, {entries} queue entries, {notifs} notifications")


async def ensure_demo_users(db) -> dict[str, object]:
    now = datetime.now(timezone.utc)
    ids: dict[str, object] = {}
    for netid, display_name in DEMO_PEOPLE:
        doc = {
            "netid": netid,
            "password_hash": hash_password(DEMO_PASSWORD),
            "display_name": display_name,
            "onboarding_complete": True,
            "is_demo": True,
            "created_at": now,
            "updated_at": now,
        }
        result = await db.users.insert_one(doc)
        ids[netid] = result.inserted_id
    return ids


async def seed_demo(db) -> None:
    existing = await db.users.count_documents({"is_demo": True})
    if existing:
        print(f"{existing} demo users already exist — run with --reset to clear and reseed")
        return

    campus = await db.campuses.find_one({"slug": "busch"}) or await db.campuses.find_one()
    if campus is None:
        print("No campuses found — run `python -m scripts.seed` first")
        return

    machines = await db.machines.find(
        {"campus_id": campus["_id"], "is_active": {"$ne": False}}
    ).sort("name", 1).to_list(length=None)
    if len(machines) < len(SCENARIOS):
        print(f"Only {len(machines)} machines found on {campus['name']} — run `python -m scripts.seed` first")
        return

    user_ids = await ensure_demo_users(db)

    print(f"Seeding demo people on {campus['name']}:")
    for machine, roles in zip(machines, SCENARIOS):
        print(f"\n{machine['name']}:")
        for netid, role in roles:
            uid = user_ids[netid]
            entry = await service.join_queue(db, manager, machine["_id"], uid)
            if role in ("active", "resting"):
                entry = await service.check_in(db, manager, entry["_id"], uid)
            if role == "resting":
                entry = await service.start_rest(db, manager, entry["_id"], uid)
            if role == "pending":
                # default grace deadline is short (minutes); stretch it so it survives a live demo
                deadline = datetime.now(timezone.utc) + timedelta(seconds=1200)
                await db.queue_entries.update_one({"_id": entry["_id"]}, {"$set": {"grace_deadline": deadline}})
            print(f"  {DISPLAY_NAME_BY_NETID[netid]}: {ROLE_LABEL[role]}")

    await db.queue_entries.update_many(
        {"user_ids": {"$in": list(user_ids.values())}}, {"$set": {"is_demo": True}}
    )

    print(f"\nLog in as yourself and open the machines above to see them in the queue.")
    print(f"(Demo accounts also log in: netid one of {sorted(DEMO_NETIDS)}, password '{DEMO_PASSWORD}')")
    print("Run `python -m scripts.seed_demo --clear` to remove all demo data again.")


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--clear", action="store_true", help="remove demo people + their queue entries, then exit")
    ap.add_argument("--reset", action="store_true", help="remove existing demo data first, then seed fresh")
    args = ap.parse_args()

    await connect_db()
    db = get_db()

    if args.clear or args.reset:
        await clear_demo_data(db)
        if args.clear:
            await close_db()
            return

    await seed_demo(db)
    await close_db()


if __name__ == "__main__":
    asyncio.run(main())
