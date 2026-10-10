import hmac
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.config import settings
from app.db import get_db
from app.vision.schemas import VisionEventBatch
from app.vision.service import handle_vision_event
from app.ws.manager import manager

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/vision", tags=["vision"])


def require_vision_key(authorization: str | None = Header(default=None)) -> None:
    if not settings.vision_events_api_key:
        return
    token = authorization[7:] if authorization and authorization.lower().startswith("bearer ") else ""
    if not hmac.compare_digest(token.encode(), settings.vision_events_api_key.encode()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or missing vision API key")


@router.post("/events", dependencies=[Depends(require_vision_key)])
async def vision_events(batch: VisionEventBatch, db: AsyncIOMotorDatabase = Depends(get_db)):
    for event in batch.events:
        await handle_vision_event(db, manager, event)
    return {"received": len(batch.events)}


@router.get("/machines", dependencies=[Depends(require_vision_key)])
async def list_machines(db: AsyncIOMotorDatabase = Depends(get_db)):
    """Machine ids for the vision service's cameras.json (vision/scripts/list_machines.py)."""
    campuses = {c["_id"]: c["name"] for c in await db.campuses.find().to_list(length=None)}
    machines = await db.machines.find().sort([("campus_id", 1), ("name", 1)]).to_list(length=None)
    return [{"id": str(m["_id"]), "name": m["name"], "campus": campuses.get(m["campus_id"])} for m in machines]
