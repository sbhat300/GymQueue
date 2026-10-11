# Gym vision service

Face scan, face recognition at each machine, and presence tracking. It drives the GymQueue
queue automatically: the app has no Check in / Finish / I'm back buttons, the camera does it.
Runs on the laptop's CPU (InsightFace / ArcFace). Cameras are Freenove ESP32-S3 boards on a
phone hotspot, or the laptop webcam until those arrive.

```
ESP32 / webcam ──/capture──► vision service :8001 ──POST /api/vision/events──► GymQueue backend :8000 ──WebSocket──► app
                             detect → recognise →        (Bearer key)            check in / finish /
                             track → presence  ◄── rest / release / enroll ───    return from rest
```

## What the camera does in the app (`backend/app/vision/`)

| camera reports | queue does |
|---|---|
| `user_arrived` while it's your turn (or you're in the end-of-use grace) | **checks you in / resumes your turn** |
| `user_left` (unseen for `AWAY_GRACE_S`, 15 s) while active | **finishes your turn**: end-of-use grace starts |
| `rest_ended` with reason `returned` | **ends your rest** |
| `heartbeat` | head count on camera, used for **busy times** (walk-ins included) |

The backend keeps the camera in sync: tapping **Rest** calls `POST /machines/{id}/rest` here (so
walking off during a rest doesn't end your turn), and leaving the queue or a grace expiring
calls `/release`. Face scan happens in the app after sign-up (`/setup-face`), proxied through
the backend so a browser can only enroll its own account.

## Run the whole thing (no ESP32 needed)

Keys (any long random strings), matching pairs:

| `backend/.env` | `vision/.env` |
|---|---|
| `VISION_URL=http://localhost:8001` | (`PORT=8001`, the default) |
| `VISION_API_KEY=<key A>` | `VISION_API_KEY=<key A>` |
| `VISION_EVENTS_API_KEY=<key B>` | `BACKEND_API_KEY=<key B>` |

```bash
# backend (needs MongoDB: `docker compose up -d` from the repo root)
cd backend && .venv/bin/uvicorn app.main:app --port 8000
cd frontend && npm run dev                  # needs frontend/.env (copy .env.example)
cd vision && ./run.sh                       # vision service on :8001
```

Sign up in the app; after choosing a name you're taken to the face scan. Then point a camera
at a machine in `cameras.json` (machine ids: `PYTHONPATH= .venv/bin/python scripts/list_machines.py`):
```json
[{"machine_id": "<id>", "name": "Bench Press 1", "source": "webcam:0"}]
```
Restart `./run.sh`, join Bench Press 1's queue, and sit in front of the camera: you're
checked in. Walk away and your turn wraps up ~15 s later.
Annotated live view: http://localhost:8001/machines/<machine id>/stream

The face model (~280 MB) downloads to `~/.insightface` on first use.

### Without the backend
For tuning the camera on its own, `BACKEND_URL` can be left empty (events are only printed):
```bash
PYTHONPATH= .venv/bin/python scripts/enroll_cli.py --user-id me --name "Nishant"
PYTHONPATH= .venv/bin/python scripts/live.py --source webcam:0 --grace 10
```
Walk out of frame → `user_left` after 10 s. Press `r` to start a 20 s rest.

### Test the ESP32 path before the board arrives
`scripts/esp32_sim.py` serves the laptop webcam on the exact same endpoints as the firmware:
```bash
PYTHONPATH= .venv/bin/python scripts/esp32_sim.py --source webcam:0 --port 8081
# cameras.json: {"machine_id": "<machine id>", "source": "esp32:http://127.0.0.1:8081"}
```
Run it on a second laptop on the hotspot to test over real Wi-Fi.

### Tests
```bash
PYTHONPATH= .venv/bin/python -m pytest -q
```

## Camera sources (`cameras.json`)

| source | use |
|---|---|
| `esp32:http://192.168.43.50` | ESP32 camera board with `firmware/esp32cam` (polls `/capture`) |
| `esp32:http://gymcam-bench1.local` | same, via mDNS name |
| `mjpeg:http://host:81/stream` | any MJPEG stream |
| `snapshot:http://phone:8080/shot.jpg` | any URL returning a JPEG (phone IP-webcam apps work as a backup camera) |
| `webcam:0` | laptop/USB webcam at 1280x720 (`webcam:0@1920x1080` for another size) |
| `file:clip.mp4` | looping video, for testing |

## Face registration (part 2)

Five poses: **center, left, right, up, down**, 3 good frames each. Each frame is checked for:
exactly one face, size (move closer), blur (hold still), the requested head turn *relative to
that user's own neutral pose*, and that it is still the same person who started. On finish,
one averaged 512-d embedding per pose is stored, and the scan is refused if that face is
already registered to a different account.

**Web signup flow** (the frontend captures webcam frames; the backend proxies to here with
the logged-in user's id, so nobody can enroll as someone else):

```
POST /enroll/start            {"user_id": "<uuid>"}            → {session_id, step, instruction, ...}
POST /enroll/{sid}/frame      {"image": "data:image/jpeg;base64,..."}   (or raw image/jpeg body)
      → {step, instruction, accepted, message, progress (0-1), done, face: {bbox, yaw, pitch}}
      send ~3-4 frames/s; show `message` to the user; stop when done == true
POST /enroll/{sid}/finish     → {stored: true}   | 409 face already registered | 400 incomplete
DELETE /faces/{user_id}       delete someone's biometric data
```

## Presence & rest tracking (part 7)

Per machine, every processed frame:
- **arrival**: a recognised user seen `ARRIVE_HITS` times within `ARRIVE_WINDOW_S` → `user_arrived`
  (filters out people walking past).
- **tracking**: faces are followed frame-to-frame, so a recognised user stays recognised while
  turned away mid-set.
- **leaving**: not seen for `AWAY_GRACE_S` → `user_left`.
- **rest**: when the backend reports a rest (`POST /machines/{id}/rest`), absence doesn't count
  until the rest ends; then the normal grace period applies. Coming back early sends
  `rest_ended: returned`. Max `MAX_RESTS` (6) per session. Tapping "rest" while still in front
  of the camera does not cancel it.
- **unknown face** persistently at the machine → `unknown_face` (rate-limited).
- **camera offline** → `camera_offline`; that time is *not* counted as the user being away.

## Rep counting (shoulder press)

Add `"exercise": "shoulder_press"` to a camera in your cameras file:
```json
{"machine_id": "<Shoulder Press id>", "name": "Shoulder Press", "source": "esp32:http://127.0.0.1:8081", "exercise": "shoulder_press"}
```
That camera then also runs a body-pose model (MediaPipe Pose, ~40 ms per frame; the 6 MB model
downloads to `data/models/` on first use). A rep = arms go from bent with hands around ear height
to straight with hands well overhead, each held for 2 frames. Reps go to whoever the camera
recognises on the machine; a set ends after 15 s without a rep or when they walk away.

Events: `rep_counted` (`user_id`, `exercise`, `reps` so far) on every rep, and `set_completed`
(`user_id`, `exercise`, `reps`, `started_at`, `ended_at`) at the end of a set. The backend logs
the set in that user's workout for the day; shoulder press reps can only come from the camera.

Camera placement matters: the person's shoulders, elbows and wrists must be in view (front-on,
waist up). The live view draws the arms and shows the elbow angle and hand height it's reading.

## Interface with the backend

### Events this service sends
`POST {BACKEND_URL}/api/vision/events`, header `Authorization: Bearer {BACKEND_API_KEY}`, body
`{"events": [...]}`. `machine_id` and `user_id` are GymQueue (MongoDB) ids. Every event has
`id`, `type`, `machine_id`, `ts` (unix seconds) and `at` (ISO-8601 UTC).

| type | extra fields | used by the backend for |
|---|---|---|
| `user_arrived` | `user_id`, `confidence` | check in / resume |
| `user_left` | `user_id`, `last_seen`, `was_resting` | finish turn |
| `rest_ended` | `user_id`, `reason` (`returned`/`expired`/`cancelled`) | `returned` = back from rest |
| `heartbeat` (every `HEARTBEAT_S`) | `present_user_ids`, `unknown_faces`, `users[]`, `camera_online`, `fps` | busy-times head count |
| `rest_started`, `rest_expired`, `unknown_face`, `camera_offline`/`camera_online` | | informational |

`GET {BACKEND_URL}/api/vision/machines` (same key) lists machine ids for `cameras.json`.

### This service's own API
Auth: `Authorization: Bearer {VISION_API_KEY}` (or `X-API-Key`, or `?key=` for `<img>` tags).
Empty `VISION_API_KEY` = open, for local dev.

```
POST   /enroll/start           {"user_id": "..."}        guided face scan (the app's /setup-face page, via the backend)
POST   /enroll/{sid}/frame     {"image": "data:image/jpeg;base64,..."}  → instruction, progress, done
POST   /enroll/{sid}/finish    → stored | 409 face already registered | 400 incomplete
POST   /machines/{id}/rest     {"user_id", "seconds"}   backend: user tapped Rest
DELETE /machines/{id}/rest     {"user_id"}              backend: rest ended
POST   /machines/{id}/release  {"user_id"}              backend: user's turn is over
DELETE /faces/{user_id}        delete someone's face data
GET    /machines               status of every camera + who is on camera
GET    /machines/{id}/stream   annotated MJPEG (demo view)  ·  /frame.jpg single frame
POST   /identify               image → [{user_id, score, bbox}]
GET    /events/recent          last events (debugging)
GET    /health                 no auth
```

### Face storage
Faces are stored in `data/faces.json` on the laptop running this service (git-ignored, since
it's biometric data). `FACE_STORE=supabase` is also supported (see `gymvision/store.py`).

## Recognising people further away
A face has to be roughly **25–35 px wide** in the frame to be recognised. What gets you there:

1. **Resolution.** Webcams are opened at 1280x720 (`webcam:0@1920x1080` for more), and the
   ESP32 firmware sends 1280x720 (`FRAMESIZE_HD`). At 640x480, faces are half as wide and anyone
   past about 2 m is lost.
2. **`roi` per camera (biggest win, no extra CPU).** Tell it where the user is on the machine:
   ```json
   {"machine_id": "bench-1", "source": "esp32:http://...", "roi": [0.25, 0.1, 0.75, 0.9]}
   ```
   `[x1, y1, x2, y2]` are fractions of the frame. Only that area is searched, so the detector
   effectively zooms in, and people walking past in the background are ignored. The live view
   draws the box, and each face label shows its width in px, so you can tune it. Try it with
   `scripts/live.py --roi 0.25,0.1,0.75,0.9`.
3. **Re-enroll after updating.** The scan now also stores low-resolution ("far") copies of the
   center/left/right poses, so a close-up enrollment matches a face seen from across the room.
   Enrollments made before this change don't have them.
4. **Averaging over frames.** Each tracked face is identified from a running average of its
   recent frames rather than one blurry frame. This needs no setup.

Measured on a synthetic test (a different view of the enrolled face, ESP32-style JPEG, sensor
noise): the old 640x480 setup lost the face beyond ~70 px at 1280 wide. Full-frame 1280x720
recognises down to ~35 px, and with `roi` down to ~26 px.

If it's still short, set `DET_SIZE=960` (about 35% more CPU per frame) so the detector looks at
the full frame in more detail.

## Tuning notes
- `MATCH_THRESHOLD` 0.45 suits buffalo_l. If strangers get matched, raise it; if you're often
  "unknown", lower it toward 0.38 or re-enroll under the gym's lighting.
- Mount the camera at head height, angled at where the user's face is during the exercise.
  A user lying flat on a bench, or facing away on a cable machine, is invisible, and the grace
  period is what covers that. Set `AWAY_GRACE_S` per demo.
- Light the face from the front. A bright window behind the user hurts more than distance does.
- CPU cost is about 200 ms per 1280x720 frame with buffalo_l. Lower `MAX_FPS` with several
  cameras, or use `INSIGHTFACE_MODEL=buffalo_s`.
