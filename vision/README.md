# Gym vision service

Face scan at signup, face recognition at each machine, and presence/rest tracking with
grace periods. Runs on the laptop's CPU (InsightFace / ArcFace). Cameras are Freenove ESP32-S3 camera boards on
a phone hotspot, or the laptop webcam until those arrive.

```
ESP32-CAM ──HTTP /capture──► vision service (this) ──POST /api/vision/events──► Next.js backend ──► Supabase
 (hotspot)                    detect → recognise →        (Bearer BACKEND_API_KEY)       (queue logic,
                              track → presence/grace                                     notifications)
signup page ──frames──► Next.js ──► /enroll/* (this) ──embeddings──► Supabase face_embeddings
backend ──► /machines/{id}/rest   (approved rest → camera won't release the machine)
```

## Quick start (no ESP32 needed)

```bash
cd vision
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env        # optional; defaults work for local testing
```
The face model (~280 MB) downloads to `~/.insightface` on first use.

1. **Enroll yourself** (opens a webcam window, guides you through 5 head poses):
   ```bash
   PYTHONPATH= .venv/bin/python scripts/enroll_cli.py --user-id me --name "Nishant"
   ```
2. **Watch recognition + presence live** (events print in the terminal):
   ```bash
   PYTHONPATH= .venv/bin/python scripts/live.py --source webcam:0 --grace 10
   ```
   Walk out of frame → `user_left` after 10 s. Press `r` to start a 20 s rest.
3. **Run the full service** (uses `cameras.json`):
   ```bash
   ./run.sh
   # open http://localhost:8000/machines/bench-1/stream  for the annotated live view
   ```

### Test the ESP32 path before the board arrives
`scripts/esp32_sim.py` serves the laptop webcam on the exact same endpoints as the firmware:
```bash
PYTHONPATH= .venv/bin/python scripts/esp32_sim.py --source webcam:0 --port 8081
# cameras.json: {"machine_id": "bench-1", "source": "esp32:http://127.0.0.1:8081"}
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
- **rest**: after the backend approves a rest, absence doesn't count until the rest ends;
  then the normal grace period applies. Coming back early ends the rest. Max `MAX_RESTS` (6)
  per session. Tapping "rest" while still in front of the camera does not cancel it.
- **unknown face** persistently at the machine → `unknown_face` (rate-limited).
- **camera offline** → `camera_offline`; that time is *not* counted as the user being away.

## Contract for the backend

### Events this service sends
`POST {BACKEND_URL}/api/vision/events`, header `Authorization: Bearer {BACKEND_API_KEY}`,
body `{"events": [...]}`. Every event has `id` (for de-duplication), `type`, `machine_id`,
`ts` (unix seconds), and `at` (ISO-8601 UTC).

| type | extra fields | suggested backend action |
|---|---|---|
| `user_arrived` | `user_id`, `confidence` | if user is next/called → check in; otherwise → notify them "not your turn" (wrong person) |
| `user_left` | `user_id`, `last_seen`, `was_resting` | end their session, release machine, notify next in queue |
| `rest_started` | `user_id`, `rest_until`, `rests_used`, `rests_left` | show rest countdown |
| `rest_ended` | `user_id`, `reason` (`returned`/`expired`/`cancelled`) | back to "in use" |
| `rest_expired` | `user_id`, `grace_until` | notify user "rest over, come back" |
| `unknown_face` | `count` | flag "unregistered person on machine" |
| `camera_offline` / `camera_online` | `error` | show camera status |
| `heartbeat` (every `HEARTBEAT_S`) | `users[]`, `present_user_ids`, `camera_online`, `fps` | optional: live "on camera" indicator |

Example:
```json
{"events": [{"id": "9f2c…", "type": "user_arrived", "machine_id": "bench-1",
             "ts": 1791653118.7, "at": "2026-10-10T17:25:18Z", "user_id": "4b1e…", "confidence": 0.71}]}
```

### Commands the backend can send here
Auth: `Authorization: Bearer {VISION_API_KEY}` (or `X-API-Key`, or `?key=` for `<img>` tags).

```
POST   /machines/{id}/rest     {"user_id": "...", "seconds": 120}   → rest_started | 409 limit reached / already resting
DELETE /machines/{id}/rest     {"user_id": "..."}                   end rest early
POST   /machines/{id}/release  {"user_id": "..."}                   user left the queue; forget them
GET    /machines               status of every camera + who is present
GET    /machines/{id}/stream   annotated MJPEG (demo view)  ·  /frame.jpg single frame
POST   /identify               image → [{user_id, score, bbox}]
GET    /events/recent          last events (debugging)
GET    /health                 no auth
```

### Supabase table (owned by the DB side)
With `FACE_STORE=supabase` this service reads/writes `face_embeddings` through PostgREST using
the service-role key. It expects the columns `user_id`, `pose` (text), and `embedding`
(`vector(512)` or `float8[]`), with `unique (user_id, pose)`. Turn RLS on with **no** client
policies so only the service role can read biometric data.

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
