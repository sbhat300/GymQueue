## Inspiration

If you've ever lifted at a Rutgers rec center around 6 p.m., you know the routine: circle the racks, ask "how many sets left?", then hover awkwardly until someone finishes. Nobody actually knows who's next, and the person who asked first usually loses to the person standing closest.

We wanted the gym to hold your place in line for you. And since the person using a machine is already standing right in front of it, we asked a simple question: **what if the machine could just see who's on it?**

## What it does

GymQueue is a virtual line for shared gym equipment, run by cameras instead of buttons.

- **Join from your phone.** Pick a campus and a machine, join its queue, and see a live estimated wait. You can also ask to work in with whoever is on it.
- **The camera checks you in.** When it's your turn, just walk up. A small ESP32 camera on the machine recognizes your face and starts your turn. There's no check-in button.
- **It counts your reps.** On the shoulder press, a pose model counts reps, groups them into sets, and logs them to your daily workout.
- **It notices when you leave.** Walk away for 15 seconds and your turn wraps up. Tap **Rest** and it waits for you instead (up to 6 rests). The next person is notified in real time.
- **Busy times.** Camera head counts, including walk-ins who never joined the queue, feed an hourly busy-times chart.
- **Heart rate (experimental).** We're also working on contactless heart rate during sets using Presage's SmartSpectra SDK (more on that under challenges).

## How we built it

GymQueue is three services plus camera firmware:

```
ESP32-S3 camera ──JPEG──► Vision service ──events──► Backend ──WebSocket──► React app
                          (Python, CPU)               (FastAPI + MongoDB)
```

### Backend: a race-safe queue

The queue is a state machine: `waiting → grace → active ⇄ resting → done`. Three things can change it at once: users tapping buttons, camera events, and a background scheduler that expires grace and rest periods. So we never read-then-write. Every transition is a single atomic `find_one_and_update` that only succeeds if the entry is still in the expected state with the expected version number, and a partial unique index guarantees at most one owner per machine at the database level.

The estimated wait assumes each turn takes $T \in [10, 15]$ minutes, and each extra partner working in adds $\Delta$:

$$
W = \sum_{i \,\in\, \text{turns ahead}} \Big( T + (n_i - 1)\,\Delta \Big)
$$

where $n_i$ is the number of people sharing turn $i$. We compute it with both $T_{\min}$ and $T_{\max}$ to show a range.

### Vision service: who is on the machine?

**Face recognition.** InsightFace detects faces and ArcFace turns each one into a 512-dimensional embedding. A face matches an enrolled user when the cosine similarity clears a threshold:

$$
\operatorname{sim}(\mathbf{a}, \mathbf{b}) = \frac{\mathbf{a} \cdot \mathbf{b}}{\lVert \mathbf{a} \rVert \, \lVert \mathbf{b} \rVert} \;\ge\; 0.45
$$

Faces are tracked frame to frame by bounding-box overlap (IoU), so you stay recognized while you look away mid-set.

**Presence.** Raw detections are noisy, so every state change has to be confirmed. You "arrive" after 3 sightings within 4 seconds, which filters out people walking past. You "leave" after 15 seconds unseen, and while you're resting, being away doesn't count at all.

**Enrollment.** After sign-up, a guided Face ID-style scan captures five poses (center, left, right, up, down). It rejects blurry, too-small, or wrong-angle frames and refuses a face that's already registered to another account.

**Rep counting.** MediaPipe Pose gives us shoulder $\mathbf{s}$, elbow $\mathbf{e}$, and wrist $\mathbf{w}$. We compute the elbow angle

$$
\theta = \arccos\!\left( \frac{(\mathbf{s} - \mathbf{e}) \cdot (\mathbf{w} - \mathbf{e})}{\lVert \mathbf{s} - \mathbf{e} \rVert \, \lVert \mathbf{w} - \mathbf{e} \rVert} \right)
$$

and the wrist height measured in shoulder widths, so it doesn't matter how far you stand from the camera:

$$
h = \frac{y_{\text{shoulder}} - y_{\text{wrist}}}{\lVert \mathbf{s}_L - \mathbf{s}_R \rVert}
$$

The arms are **up** when $\theta > 150^\circ$ and $h > 1.2$, and **down** when $\theta < 115^\circ$ and $h < 0.9$. A rep is down → up, with each position held for 2 frames. The gap between the two thresholds acts as hysteresis, so a wobble at lockout can't count twice.

### Firmware and frontend

The ESP32-S3 boards join a phone hotspot and serve `/capture` (one JPEG) and `/stream` (MJPEG). A simulator script serves a laptop webcam on the exact same endpoints, so we could build the whole pipeline before the boards arrived. The frontend is React + Vite + TypeScript, in Rutgers scarlet.

## Challenges we ran into

**Recognizing faces from across the room.** At 640×480, a face two meters away is about 17 pixels wide, well below the roughly 25–35 px that recognition needs. We fixed it three ways: raising cameras to 720p, adding a per-camera region of interest that crops to where the lifter actually sits (a free zoom that also ignores people in the background), and storing low-resolution "far" copies of each enrollment pose so a close-up scan still matches a distant face.

**Cheap hardware is unpredictable.** Some of our ESP32 boards had no hardware JPEG encoder, so the firmware falls back to software encoding at a lower resolution. Wi-Fi was flaky enough that each camera can list several sources (laptop hotspot, iPhone hotspot, USB cable) and the service moves to the next one when a source goes quiet.

**Rep counting up close.** Near the camera, your hands leave the top of the frame at lockout. Elbows stay in view, so we added elbow height as a second signal for "up".

**Security vs. friction.** We built a liveness check that required a head turn before check-in, to stop someone from holding up a photo. It made walking up to a machine feel slow, so we cut it for the demo and kept the security on the server side instead: only the person a queue slot belongs to can act on it.

**Heart rate.** This one fought us the whole way. Presage's Python package conflicted with the MediaPipe build we use for pose, so we talked to their REST API directly, and it kept coming back empty. The culprit turned out to be OpenCV's `VideoWriter`, which *silently drops* every frame whose size differs from the first one. Our face crops change size every frame, so we were uploading nearly empty videos. We then moved to Presage's officially supported C++ SDK: Python writes each set as a clip plus a per-frame timestamp file, calls a small C++ program we wrote, and reads back one line of JSON. That finally ran, and immediately told us something new: it needs at least 25 fps.

## What we learned

**Theory and practice disagree on frame rate.** A heart rate of up to 200 bpm is about $3.3\,\text{Hz}$, so Nyquist says sampling at $f_s > 2 \times 3.3 \approx 6.7$ fps should be enough in principle. In practice the SDK rejects anything below $25$ fps, and a $20 camera streaming 720p over Wi-Fi delivers about $10$. Hardware constraints belong at the start of the design, not the end.

**Real-world signals need debouncing everywhere.** Arrival hits, the leave grace period, rep confirmation frames, and threshold hysteresis are all the same idea: never act on a single noisy frame.

**Push correctness into the database.** Conditional atomic updates and a unique index did more for reliability than any amount of careful application code.

**Silent failures are the worst failures.** The `VideoWriter` bug cost us hours because nothing ever errored. Now we check that the output actually contains what we put in.

**Privacy is part of the product.** Face data stays on the machine running the vision service, can be deleted on request, and a browser can only ever enroll its own account.
