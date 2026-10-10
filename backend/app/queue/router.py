from fastapi import APIRouter, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.db import get_db
from app.deps import get_current_user
from app.models.common import oid
from app.queue import service
from app.queue.schemas import entry_to_public, resolve_users_by_id
from app.ws.manager import manager

router = APIRouter(tags=["queue"])


@router.get("/machines/{machine_id}/queue")
async def get_queue(
    machine_id: str,
    _user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    entries = await service.get_live_queue_for_machine(db, oid(machine_id, "machine_id"))
    all_user_ids = [uid for e in entries for uid in e["user_ids"]]
    users_by_id = await resolve_users_by_id(db, all_user_ids)
    return [entry_to_public(e, users_by_id) for e in entries]


@router.post("/machines/{machine_id}/queue/join")
async def join_queue(
    machine_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    entry = await service.join_queue(db, manager, oid(machine_id, "machine_id"), user["_id"])
    users_by_id = await resolve_users_by_id(db, entry["user_ids"])
    return entry_to_public(entry, users_by_id)


@router.post("/machines/{machine_id}/queue/{entry_id}/leave")
async def leave_queue(
    machine_id: str,
    entry_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    entry = await service.leave_queue(db, manager, oid(entry_id, "entry_id"), user["_id"])
    users_by_id = await resolve_users_by_id(db, entry["user_ids"])
    return entry_to_public(entry, users_by_id)


@router.post("/machines/{machine_id}/queue/{entry_id}/check-in")
async def check_in(
    machine_id: str,
    entry_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    entry = await service.check_in(db, manager, oid(entry_id, "entry_id"), user["_id"])
    users_by_id = await resolve_users_by_id(db, entry["user_ids"])
    return entry_to_public(entry, users_by_id)


@router.post("/machines/{machine_id}/queue/{entry_id}/finish")
async def finish(
    machine_id: str,
    entry_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    entry = await service.finish_active(db, manager, oid(entry_id, "entry_id"), user["_id"])
    users_by_id = await resolve_users_by_id(db, entry["user_ids"])
    return entry_to_public(entry, users_by_id)


@router.post("/machines/{machine_id}/queue/{entry_id}/rest/start")
async def rest_start(
    machine_id: str,
    entry_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    entry = await service.start_rest(db, manager, oid(entry_id, "entry_id"), user["_id"])
    users_by_id = await resolve_users_by_id(db, entry["user_ids"])
    return entry_to_public(entry, users_by_id)


@router.post("/machines/{machine_id}/queue/{entry_id}/rest/return")
async def rest_return(
    machine_id: str,
    entry_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    entry = await service.return_from_rest(db, manager, oid(entry_id, "entry_id"), user["_id"])
    users_by_id = await resolve_users_by_id(db, entry["user_ids"])
    return entry_to_public(entry, users_by_id)


@router.get("/users/me/queue-entries")
async def my_queue_entries(
    user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    entries = await service.list_user_queue_entries(db, user["_id"])
    all_user_ids = [uid for e in entries for uid in e["user_ids"]]
    users_by_id = await resolve_users_by_id(db, all_user_ids)
    return [entry_to_public(e, users_by_id) for e in entries]
