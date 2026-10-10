from fastapi import APIRouter, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.db import get_db
from app.deps import get_current_user
from app.join_requests import service
from app.join_requests.schemas import request_to_public
from app.models.common import oid
from app.queue.schemas import resolve_users_by_id
from app.ws.manager import manager

router = APIRouter(tags=["join_requests"])


async def _to_public(db, doc: dict) -> dict:
    users_by_id = await resolve_users_by_id(db, [doc["requester_id"], doc["target_id"]])
    return request_to_public(doc, users_by_id)


@router.post("/machines/{machine_id}/queue/{entry_id}/join-requests")
async def create_join_request(
    machine_id: str,
    entry_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    doc = await service.create_join_request(
        db, manager, oid(machine_id, "machine_id"), oid(entry_id, "entry_id"), user["_id"]
    )
    return await _to_public(db, doc)


@router.get("/join-requests/incoming")
async def list_incoming(
    user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    docs = await service.list_incoming(db, user["_id"])
    results = []
    for doc in docs:
        results.append(await _to_public(db, doc))
    return results


@router.post("/join-requests/{request_id}/accept")
async def accept(
    request_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    doc = await service.accept_join_request(db, manager, oid(request_id, "request_id"), user["_id"])
    return await _to_public(db, doc)


@router.post("/join-requests/{request_id}/reject")
async def reject(
    request_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    doc = await service.reject_join_request(db, manager, oid(request_id, "request_id"), user["_id"])
    return await _to_public(db, doc)


@router.post("/join-requests/{request_id}/cancel")
async def cancel(
    request_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    doc = await service.cancel_join_request(db, manager, oid(request_id, "request_id"), user["_id"])
    return await _to_public(db, doc)
