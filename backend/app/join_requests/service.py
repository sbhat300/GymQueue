from datetime import datetime, timezone

from bson import ObjectId
from fastapi import HTTPException, status
from pymongo import ReturnDocument

from app.models.common import EventType, JoinRequestStatus, QueueState
from app.notifications.service import broadcast_queue_updated, notify_users
from app.queue.service import LIVE_STATE_VALUES, get_entry_or_404
from app.ws.manager import ConnectionManager


async def create_join_request(
    db, manager: ConnectionManager, machine_id: ObjectId, entry_id: ObjectId, requester_id: ObjectId
) -> dict:
    entry = await get_entry_or_404(db, entry_id)
    if entry["machine_id"] != machine_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Queue entry not found on this machine")
    if entry["state"] != QueueState.WAITING.value or len(entry["user_ids"]) != 1:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This queue slot can't accept a partner request right now")

    target_id = entry["user_ids"][0]
    if requester_id == target_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You can't request to join your own entry")

    own_entry = await db.queue_entries.find_one({"user_ids": requester_id, "state": {"$in": LIVE_STATE_VALUES}})
    if own_entry is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="You already have an active queue entry on a machine")

    existing = await db.join_requests.find_one(
        {"queue_entry_id": entry_id, "requester_id": requester_id, "status": JoinRequestStatus.PENDING.value}
    )
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="You already have a pending request for this entry")

    now = datetime.now(timezone.utc)
    doc = {
        "machine_id": machine_id,
        "queue_entry_id": entry_id,
        "requester_id": requester_id,
        "target_id": target_id,
        "status": JoinRequestStatus.PENDING.value,
        "created_at": now,
        "resolved_at": None,
    }
    result = await db.join_requests.insert_one(doc)
    doc["_id"] = result.inserted_id

    requester = await db.users.find_one({"_id": requester_id})
    await notify_users(
        db,
        manager,
        [str(target_id)],
        EventType.JOIN_REQUEST_RECEIVED,
        {
            "request_id": str(doc["_id"]),
            "machine_id": str(machine_id),
            "queue_entry_id": str(entry_id),
            "requester_id": str(requester_id),
            "requester_display_name": (requester or {}).get("display_name") or "Someone",
        },
    )
    return doc


async def _get_request_or_404(db, request_id: ObjectId) -> dict:
    req = await db.join_requests.find_one({"_id": request_id})
    if req is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Join request not found")
    return req


async def accept_join_request(db, manager: ConnectionManager, request_id: ObjectId, user_id: ObjectId) -> dict:
    req = await _get_request_or_404(db, request_id)
    if req["status"] != JoinRequestStatus.PENDING.value:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Join request already resolved")
    if req["target_id"] != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This request isn't addressed to you")

    now = datetime.now(timezone.utc)
    entry = await get_entry_or_404(db, req["queue_entry_id"])

    updated_entry = await db.queue_entries.find_one_and_update(
        {
            "_id": entry["_id"],
            "state": QueueState.WAITING.value,
            "version": entry["version"],
            "user_ids": {"$size": 1},
        },
        {"$push": {"user_ids": req["requester_id"]}, "$inc": {"version": 1}, "$set": {"updated_at": now}},
        return_document=ReturnDocument.AFTER,
    )
    if updated_entry is None:
        await db.join_requests.update_one(
            {"_id": request_id}, {"$set": {"status": JoinRequestStatus.EXPIRED.value, "resolved_at": now}}
        )
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This queue slot is no longer available")

    await db.join_requests.update_one(
        {"_id": request_id}, {"$set": {"status": JoinRequestStatus.ACCEPTED.value, "resolved_at": now}}
    )
    await db.join_requests.update_many(
        {"queue_entry_id": entry["_id"], "status": JoinRequestStatus.PENDING.value, "_id": {"$ne": request_id}},
        {"$set": {"status": JoinRequestStatus.EXPIRED.value, "resolved_at": now}},
    )

    await notify_users(
        db,
        manager,
        [str(req["requester_id"])],
        EventType.JOIN_REQUEST_ACCEPTED,
        {"request_id": str(request_id), "machine_id": str(req["machine_id"]), "queue_entry_id": str(entry["_id"])},
    )
    await broadcast_queue_updated(manager, str(req["machine_id"]))

    req["status"] = JoinRequestStatus.ACCEPTED.value
    req["resolved_at"] = now
    return req


async def reject_join_request(db, manager: ConnectionManager, request_id: ObjectId, user_id: ObjectId) -> dict:
    req = await _get_request_or_404(db, request_id)
    if req["status"] != JoinRequestStatus.PENDING.value:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Join request already resolved")
    if req["target_id"] != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This request isn't addressed to you")

    now = datetime.now(timezone.utc)
    await db.join_requests.update_one(
        {"_id": request_id}, {"$set": {"status": JoinRequestStatus.REJECTED.value, "resolved_at": now}}
    )
    await notify_users(
        db,
        manager,
        [str(req["requester_id"])],
        EventType.JOIN_REQUEST_REJECTED,
        {"request_id": str(request_id), "machine_id": str(req["machine_id"])},
    )
    req["status"] = JoinRequestStatus.REJECTED.value
    req["resolved_at"] = now
    return req


async def cancel_join_request(db, manager: ConnectionManager, request_id: ObjectId, user_id: ObjectId) -> dict:
    req = await _get_request_or_404(db, request_id)
    if req["status"] != JoinRequestStatus.PENDING.value:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Join request already resolved")
    if req["requester_id"] != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This isn't your request to cancel")

    now = datetime.now(timezone.utc)
    await db.join_requests.update_one(
        {"_id": request_id}, {"$set": {"status": JoinRequestStatus.CANCELLED.value, "resolved_at": now}}
    )
    await notify_users(
        db,
        manager,
        [str(req["target_id"])],
        EventType.JOIN_REQUEST_CANCELLED,
        {"request_id": str(request_id), "machine_id": str(req["machine_id"])},
    )
    req["status"] = JoinRequestStatus.CANCELLED.value
    req["resolved_at"] = now
    return req


async def list_incoming(db, user_id: ObjectId) -> list[dict]:
    cursor = db.join_requests.find(
        {"target_id": user_id, "status": JoinRequestStatus.PENDING.value}
    ).sort("created_at", 1)
    return await cursor.to_list(length=None)
