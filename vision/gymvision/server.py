"""HTTP API for the vision service.

Run:  python -m gymvision.server        (or ./run.sh)

Auth: every endpoint except /health requires the VISION_API_KEY, sent as
`Authorization: Bearer <key>`, `X-API-Key: <key>`, or `?key=<key>` (for <img> tags).
If VISION_API_KEY is empty the API is open (local dev only).
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import hmac
import logging
import os
import time
from contextlib import asynccontextmanager

import cv2
import numpy as np
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from .config import settings
from .enrollment import EnrollmentSession
from .engine import FaceEngine
from .events import EventSink
from .gallery import Gallery
from .store import make_store
from .tracker import RestLimitError
from .worker import MachineWorker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
log = logging.getLogger("server")
logging.getLogger("httpx").setLevel(logging.WARNING)  # otherwise every camera frame request is logged

ENROLL_SESSION_TTL_S = 600


class State:
    engine: FaceEngine
    gallery: Gallery
    sink: EventSink
    store = None
    workers: dict[str, MachineWorker] = {}
    sessions: dict[str, EnrollmentSession] = {}


S = State()


@asynccontextmanager
async def lifespan(app: FastAPI):
    S.engine = FaceEngine.shared()
    S.store = make_store()
    S.gallery = Gallery(S.store)
    S.gallery.reload()
    S.sink = EventSink()
    for cam in settings.cameras():
        S.workers[cam.machine_id] = MachineWorker(cam, S.engine, S.gallery, S.sink).start()
        log.info("machine %s <- %s", cam.machine_id, cam.source)
    if not S.workers:
        log.warning("no cameras configured (%s) - enrollment API only", settings.cameras_file)
    if not settings.api_key:
        log.warning("VISION_API_KEY is empty: API is unauthenticated (dev mode)")
    if not settings.backend_url:
        log.warning("BACKEND_URL is empty: events are logged only, not sent")
    yield
    for w in S.workers.values():
        w.stop()


app = FastAPI(title="Gym queue vision service", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
                   allow_methods=["*"], allow_headers=["*"])


LOOPBACK = {"127.0.0.1", "::1", "localhost"}


def require_key(request: Request) -> None:
    if not settings.api_key:
        return
    if settings.localhost_skips_key and request.client and request.client.host in LOOPBACK:
        return  # this laptop itself; other devices on the network still need the key
    auth = request.headers.get("authorization", "")
    given = (auth[7:] if auth.lower().startswith("bearer ") else "") \
        or request.headers.get("x-api-key", "") or request.query_params.get("key", "")
    if not hmac.compare_digest(given.encode(), settings.api_key.encode()):
        raise HTTPException(401, "invalid or missing API key")


auth = [Depends(require_key)]


def worker(machine_id: str) -> MachineWorker:
    w = S.workers.get(machine_id)
    if not w:
        raise HTTPException(404, f"no camera for machine {machine_id}")
    return w


def decode_image(data: bytes) -> np.ndarray:
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(400, "could not decode image (send JPEG/PNG)")
    return img


async def image_from_request(request: Request) -> np.ndarray:
    """Accepts a raw image body (image/jpeg) or JSON {"image": "<base64 or data URL>"}."""
    if request.headers.get("content-type", "").startswith("application/json"):
        body = await request.json()
        b64 = str(body.get("image", ""))
        if "," in b64[:100]:  # strip "data:image/jpeg;base64,"
            b64 = b64.split(",", 1)[1]
        try:
            return decode_image(base64.b64decode(b64))
        except binascii.Error:
            raise HTTPException(400, "image is not valid base64")
    return decode_image(await request.body())


# ------------------------------------------------------------------ health / status
@app.get("/health")
def health():
    return {"ok": True, "users_enrolled": S.gallery.user_count, "machines": list(S.workers),
            "events_failed": S.sink.failed}


@app.get("/machines", dependencies=auth)
def machines():
    return [w.status() for w in S.workers.values()]


@app.get("/machines/{machine_id}", dependencies=auth)
def machine(machine_id: str):
    return worker(machine_id).status()


@app.get("/machines/{machine_id}/frame.jpg", dependencies=auth)
def machine_frame(machine_id: str):
    _, jpeg = worker(machine_id).latest_jpeg()
    if jpeg is None:
        raise HTTPException(503, "no frame yet")
    return Response(jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.get("/machines/{machine_id}/stream", dependencies=auth)
def machine_stream(machine_id: str):
    """Annotated live view (MJPEG) - open in a browser for the demo."""
    w = worker(machine_id)

    # async so shutdown can cancel it (a sync generator pins a worker thread and blocks exit)
    async def gen():
        last = -1
        while True:
            seq, jpeg = w.latest_jpeg()
            if jpeg is not None and seq != last:
                last = seq
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
            await asyncio.sleep(0.05)

    return StreamingResponse(gen(), media_type="multipart/x-mixed-replace; boundary=frame")


@app.get("/machines/{machine_id}/reps-trace", dependencies=auth)
def reps_trace(machine_id: str, seconds: float = 30.0):
    """What the rep counter measured each frame (numbers only, no images) - for tuning thresholds."""
    w = worker(machine_id)
    if w.sets is None:
        raise HTTPException(404, "this camera doesn't count reps")
    since = time.time() - seconds
    c = w.sets.counter
    return {
        "thresholds": {"up": f"elbow >= {c.up_elbow_deg} deg and hands >= {c.up_wrist_height}, or elbows >= {c.up_elbow_height}",
                       "down": f"elbow <= {c.down_elbow_deg} deg and hands <= {c.down_wrist_height}, or elbows <= {c.down_elbow_height}"},
        "pose_fps": round(w.pose_fps, 1),
        "frames": [f for f in list(w.rep_trace) if f["t"] >= since],
    }


@app.get("/events/recent", dependencies=auth)
def recent_events(limit: int = 50, include_heartbeats: bool = False):
    evs = [e for e in S.sink.recent if include_heartbeats or e["type"] != "heartbeat"]
    return evs[-limit:]


# ------------------------------------------------------------------ commands from the backend
class UserBody(BaseModel):
    user_id: str


class RestBody(UserBody):
    seconds: float | None = None


@app.post("/machines/{machine_id}/rest", dependencies=auth)
def start_rest(machine_id: str, body: RestBody):
    w = worker(machine_id)
    with w.lock:
        try:
            ev = w.presence.start_rest(body.user_id, body.seconds or settings.rest_default_s, time.time())
        except RestLimitError as e:
            raise HTTPException(409, str(e))
        except ValueError as e:
            raise HTTPException(409, str(e))
    S.sink.emit([ev])
    return ev


@app.delete("/machines/{machine_id}/rest", dependencies=auth)
def end_rest(machine_id: str, body: UserBody):
    w = worker(machine_id)
    with w.lock:
        ev = w.presence.end_rest(body.user_id, time.time())
    if ev is None:
        raise HTTPException(404, "user is not resting on this machine")
    S.sink.emit([ev])
    return ev


@app.post("/machines/{machine_id}/release", dependencies=auth)
def release(machine_id: str, body: UserBody):
    w = worker(machine_id)
    with w.lock:
        w.presence.release(body.user_id)
    return {"released": body.user_id}


# ------------------------------------------------------------------ face recognition
@app.post("/identify", dependencies=auth)
async def identify(request: Request):
    """Recognise every face in one image (testing / backend use)."""
    img = await image_from_request(request)
    out = []
    for f in await run_in_threadpool(S.engine.detect, img):
        m = S.gallery.match(f.embedding)
        out.append({"user_id": m.user_id, "score": round(m.score, 3),
                    "bbox": [round(float(v), 1) for v in f.bbox]})
    return {"faces": out}


# ------------------------------------------------------------------ enrollment (part 2)
class EnrollStart(BaseModel):
    user_id: str
    label: str = ""


def session(session_id: str) -> EnrollmentSession:
    now = time.time()
    for sid in [k for k, v in S.sessions.items() if now - v.created_at > ENROLL_SESSION_TTL_S]:
        del S.sessions[sid]
    s = S.sessions.get(session_id)
    if not s:
        raise HTTPException(404, "enrollment session not found or expired")
    return s


@app.post("/enroll/start", dependencies=auth)
def enroll_start(body: EnrollStart):
    s = EnrollmentSession(body.user_id, body.label)
    S.sessions[s.id] = s
    return s.status()


@app.post("/enroll/{session_id}/frame", dependencies=auth)
async def enroll_frame(session_id: str, request: Request):
    s = session(session_id)
    img = await image_from_request(request)
    return s.status(await run_in_threadpool(s.add_frame, img, S.engine))


@app.get("/enroll/{session_id}", dependencies=auth)
def enroll_status(session_id: str):
    return session(session_id).status()


@app.post("/enroll/{session_id}/finish", dependencies=auth)
def enroll_finish(session_id: str):
    s = session(session_id)
    try:
        result = s.finish(S.store, S.gallery)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except PermissionError as e:
        raise HTTPException(409, str(e))
    del S.sessions[session_id]
    return result


@app.delete("/enroll/{session_id}", dependencies=auth)
def enroll_cancel(session_id: str):
    S.sessions.pop(session_id, None)
    return {"cancelled": True}


@app.delete("/faces/{user_id}", dependencies=auth)
def delete_face(user_id: str):
    S.store.delete_user(user_id)
    S.gallery.reload()
    return {"deleted": user_id}


def main():
    import uvicorn
    # open /stream tabs never finish on their own, so don't wait on them at Ctrl+C
    uvicorn.run(app, host=os.getenv("HOST", "0.0.0.0"), port=int(os.getenv("PORT", "8001")),
                timeout_graceful_shutdown=2)


if __name__ == "__main__":
    main()
