# GymQueue

A queueing app for shared gym equipment. Users sign up, browse campuses and machines, join a machine's queue, get notified in real time when it's their turn, check in within a grace period, take timed rest breaks (capped at 6), and hand off to the next person automatically when they're done.

Face/camera-based identity verification (enrollment and live presence tracking) is intentionally out of scope. The "wrong person on the machine" protection is implemented as a server-side authorization rule instead: only the user(s) a queue slot actually belongs to can check in or act on it.

## Stack

- **Backend**: FastAPI + Motor (async MongoDB driver), JWT auth (stub netid/password — structured so real SSO can be swapped in later), WebSockets for realtime push, a plain asyncio background task for grace/rest expiry scanning.
- **Frontend**: React + Vite + TypeScript, React Router, Context + hooks for state (no Redux).
- **DB**: MongoDB.

## Architecture

- `backend/app/queue/service.py` — the queue state machine (join → grace → active ⇄ resting → grace → done/removed). All state-changing writes use atomic `find_one_and_update` keyed on the expected current state (+ an optimistic `version` field), never read-then-write, to stay race-safe against the background scheduler.
- `backend/app/scheduler/runner.py` — a background asyncio loop that expires turn-start grace periods, rest periods, and end-of-use grace periods, promoting the next queued entry when a machine frees up.
- `backend/app/db.py` — Mongo indexes, including a partial unique index that enforces at most one "owner" (active/resting/grace) entry per machine at the database level.
- `backend/app/ws/manager.py` — WebSocket connection manager (per-user delivery + per-machine broadcast "rooms").
- `frontend/src/pages/MachineDetailPage.tsx` — the main screen: queue view, check-in, rest controls, and partner pairing requests, kept in sync live via WebSocket events.

See `backend/app/models/common.py` for the full state/event enum definitions.

## Running locally

### 1. MongoDB

```bash
docker compose up -d
```

### 2. Backend

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
.venv/bin/python -m scripts.seed   # seeds a couple of campuses + machines
.venv/bin/uvicorn app.main:app --reload
```

Backend runs on `http://localhost:8000`.

### 3. Frontend

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

Frontend runs on `http://localhost:5173`.

### 4. Try it

Open two browser sessions (e.g. one normal window + one incognito), sign up two different netids, set display names, and join the same machine's queue from both to see live turn promotion, check-in, rest periods, and partner pairing requests.

## Tests

```bash
cd backend
.venv/bin/python -m pytest
```

Tests run against a separate `gymqueue_test` database (same Mongo instance) and use short grace/rest periods so scheduler-expiry tests run quickly.

## Config

Backend env vars (`backend/.env`, see `.env.example`): `MONGODB_URI`, `MONGODB_DB_NAME`, `JWT_SECRET`, `JWT_ALGORITHM`, `JWT_EXPIRE_MINUTES`, `DEFAULT_GRACE_PERIOD_SECONDS`, `DEFAULT_REST_PERIOD_SECONDS`, `DEFAULT_MAX_RESTS`, `SCHEDULER_INTERVAL_SECONDS`, `CORS_ALLOWED_ORIGINS`.

Frontend env vars (`frontend/.env`, see `.env.example`): `VITE_API_BASE_URL`, `VITE_WS_BASE_URL`.

## Known simplifications

- One live queue entry per user system-wide (can't be queued on two machines at once).
- Partner "request to join" is only possible while the target entry is `waiting` (not mid-turn), and pairs are capped at 2 people.
- If one partner in a pair leaves mid-turn, the whole pair's turn ends (no mid-turn splitting).
- Single backend process assumed for the background scheduler (no distributed locking — not needed at this scale).
