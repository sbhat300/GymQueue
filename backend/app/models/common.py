from enum import StrEnum

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException, status


class QueueState(StrEnum):
    WAITING = "waiting"
    GRACE = "grace"
    ACTIVE = "active"
    RESTING = "resting"
    DONE = "done"
    REMOVED = "removed"


LIVE_STATES = {QueueState.WAITING, QueueState.GRACE, QueueState.ACTIVE, QueueState.RESTING}
OWNER_STATES = {QueueState.GRACE, QueueState.ACTIVE, QueueState.RESTING}


class GraceReason(StrEnum):
    TURN_START = "turn_start"
    END_OF_USE = "end_of_use"


class JoinRequestStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class EventType(StrEnum):
    YOUR_TURN = "your_turn"
    CHECKED_IN = "checked_in"
    REMOVED_FROM_QUEUE = "removed_from_queue"
    REST_STARTED = "rest_started"
    REST_RETURNED = "rest_returned"
    REST_EXPIRED = "rest_expired"
    SESSION_ENDED = "session_ended"
    JOIN_REQUEST_RECEIVED = "join_request_received"
    JOIN_REQUEST_ACCEPTED = "join_request_accepted"
    JOIN_REQUEST_REJECTED = "join_request_rejected"
    JOIN_REQUEST_CANCELLED = "join_request_cancelled"
    QUEUE_UPDATED = "queue_updated"
    REP_COUNTED = "rep_counted"
    WORKOUT_LOGGED = "workout_logged"
    VITALS_UPDATE = "vitals_update"


def oid(value: str, field: str = "id") -> ObjectId:
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid {field}")


def str_id(value: ObjectId) -> str:
    return str(value)
