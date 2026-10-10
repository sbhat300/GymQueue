from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.auth.schemas import LoginRequest, SignupRequest, TokenResponse
from app.auth.security import create_access_token, hash_password, verify_password
from app.db import get_db
from app.users.schemas import user_to_public

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=TokenResponse)
async def signup(body: SignupRequest, db: AsyncIOMotorDatabase = Depends(get_db)):
    netid = body.netid.strip().lower()
    existing = await db.users.find_one({"netid": netid})
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="netid already registered")

    now = datetime.now(timezone.utc)
    doc = {
        "netid": netid,
        "password_hash": hash_password(body.password),
        "display_name": None,
        "onboarding_complete": False,
        "created_at": now,
        "updated_at": now,
    }
    result = await db.users.insert_one(doc)
    doc["_id"] = result.inserted_id

    token = create_access_token(str(doc["_id"]))
    return TokenResponse(access_token=token, user=user_to_public(doc))


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncIOMotorDatabase = Depends(get_db)):
    netid = body.netid.strip().lower()
    user = await db.users.find_one({"netid": netid})
    if user is None or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid netid or password")

    token = create_access_token(str(user["_id"]))
    return TokenResponse(access_token=token, user=user_to_public(user))
