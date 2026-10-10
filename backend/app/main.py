import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth.router import router as auth_router
from app.campuses.router import router as campuses_router
from app.config import settings
from app.db import close_db, connect_db, get_db
from app.join_requests.router import router as join_requests_router
from app.machines.router import router as machines_router
from app.notifications.router import router as notifications_router
from app.queue.router import router as queue_router
from app.scheduler.runner import scheduler_loop
from app.users.router import router as users_router
from app.vision.enroll_router import router as vision_enroll_router
from app.vision.router import router as vision_router
from app.ws.manager import manager
from app.ws.router import router as ws_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_db()
    task = asyncio.create_task(scheduler_loop(get_db(), manager, settings.scheduler_interval_seconds))
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    await close_db()


app = FastAPI(title="GymQueue API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(users_router)
app.include_router(campuses_router)
app.include_router(machines_router)
app.include_router(queue_router)
app.include_router(join_requests_router)
app.include_router(notifications_router)
app.include_router(vision_router)
app.include_router(vision_enroll_router)
app.include_router(ws_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
