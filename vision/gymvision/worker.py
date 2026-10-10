"""One thread per gym machine: camera -> detect -> recognise -> track -> presence events."""
from __future__ import annotations

import logging
import threading
import time

import cv2
import numpy as np

from .camera import FrameSource, open_source
from .config import CameraConfig, settings
from .engine import FaceEngine
from .events import EventSink, make_event
from .gallery import Gallery
from .tracker import UNKNOWN, FaceTracker, PresenceTracker

log = logging.getLogger(__name__)

CAMERA_OFFLINE_S = 5.0


class MachineWorker:
    def __init__(self, cam: CameraConfig, engine: FaceEngine, gallery: Gallery, sink: EventSink,
                 source: FrameSource | None = None):
        self.cam = cam
        self.machine_id = cam.machine_id
        self.engine, self.gallery, self.sink = engine, gallery, sink
        self.source = source or open_source(cam.source)
        self.faces = FaceTracker()
        self.presence = PresenceTracker(cam.machine_id)
        self.lock = threading.Lock()  # guards self.presence (camera thread vs API requests)
        self.fps = 0.0
        self.unknown_faces = 0   # unrecognised people in the latest frame (walk-ins count for busy times)
        self.offline_since: float | None = None
        self._jpeg: bytes | None = None
        self._jpeg_seq = 0
        self._stop = threading.Event()

    def start(self) -> "MachineWorker":
        self.source.start()
        threading.Thread(target=self._run, name=f"machine:{self.machine_id}", daemon=True).start()
        return self

    def stop(self) -> None:
        self._stop.set()
        self.source.stop()

    # ---------------------------------------------------------------- loop
    def _run(self) -> None:
        seq, last_frame_at, last_hb = -1, time.time(), 0.0
        min_dt = 1.0 / settings.max_fps
        while not self._stop.is_set():
            t0 = time.time()
            seq_new, _, frame = self.source.latest(seq)
            if frame is None:
                self._check_offline(t0, last_frame_at)
                self._stop.wait(0.02)
                continue
            seq = seq_new
            if self.offline_since is not None:
                with self.lock:
                    self.presence.shift_time(t0 - last_frame_at)
                self.sink.emit([make_event("camera_online", self.machine_id)])
                self.offline_since = None
            last_frame_at = t0
            try:
                self._process(frame, t0)
            except Exception:
                log.exception("machine %s: frame processing failed", self.machine_id)
            if t0 - last_hb >= settings.heartbeat_s:
                last_hb = t0
                self.sink.emit([self.heartbeat(t0)])
            dt = time.time() - t0
            self.fps = 0.8 * self.fps + 0.2 * (1.0 / max(dt, 1e-3))
            self._stop.wait(max(0.0, min_dt - dt))

    def _check_offline(self, now: float, last_frame_at: float) -> None:
        if self.offline_since is None and now - last_frame_at > CAMERA_OFFLINE_S:
            self.offline_since = last_frame_at
            log.warning("machine %s: camera offline (%s)", self.machine_id, self.source.last_error)
            self.sink.emit([make_event("camera_offline", self.machine_id, error=self.source.last_error)])

    def _roi_px(self, frame: np.ndarray) -> tuple[int, int, int, int] | None:
        if not self.cam.roi:
            return None
        h, w = frame.shape[:2]
        x1, y1, x2, y2 = self.cam.roi
        return int(x1 * w), int(y1 * h), int(x2 * w), int(y2 * h)

    def _process(self, frame: np.ndarray, now: float) -> None:
        self.gallery.maybe_reload()
        roi = self._roi_px(frame)
        if roi:
            x1, y1, x2, y2 = roi
            faces = self.engine.detect(frame[y1:y2, x1:x2])
            for f in faces:  # back to full-frame coordinates
                f.bbox = f.bbox + np.array([x1, y1, x1, y1], np.float32)
                f.kps = f.kps + np.array([x1, y1], np.float32)
        else:
            faces = self.engine.detect(frame)
        tracks = self.faces.update(faces, now, self.gallery.match)

        seen: dict[str, float] = {}
        unknown = 0
        for t in tracks:
            uid = t.identity
            if uid == UNKNOWN:
                unknown += 1
            else:
                seen[uid] = max(seen.get(uid, 0.0), t.last_score)
        self.unknown_faces = unknown
        with self.lock:
            events = self.presence.observe(now, seen, unknown)
        self.sink.emit(events)
        self._annotate(frame, tracks, now)

    # ---------------------------------------------------------------- status / debug view
    def heartbeat(self, now: float) -> dict:
        with self.lock:
            users = self.presence.snapshot(now)
        return make_event("heartbeat", self.machine_id, now, users=users,
                          present_user_ids=[u["user_id"] for u in users if u["seconds_unseen"] < 2.0],
                          unknown_faces=self.unknown_faces if self.offline_since is None else 0,
                          camera_online=self.offline_since is None, fps=round(self.fps, 1))

    def status(self) -> dict:
        hb = self.heartbeat(time.time())
        return {"machine_id": self.machine_id, "name": self.cam.name, "source": self.cam.source,
                "camera_online": hb["camera_online"], "camera_error": self.source.last_error,
                "fps": hb["fps"], "users": hb["users"]}

    def _annotate(self, frame: np.ndarray, tracks, now: float) -> None:
        img = frame.copy()
        roi = self._roi_px(frame)
        if roi:
            cv2.rectangle(img, roi[:2], roi[2:], (200, 200, 200), 1)
        for t in tracks:
            x1, y1, x2, y2 = t.bbox.astype(int)
            known = t.identity != UNKNOWN
            color = (60, 200, 60) if known else (40, 40, 230)
            name = (self.gallery.label(t.identity) or t.identity[:8]) if known else "unknown"
            cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
            cv2.putText(img, f"{name} {t.last_score:.2f} ({x2 - x1}px)", (x1, max(15, y1 - 8)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
        with self.lock:
            snap = self.presence.snapshot(now)
        y = 22
        cv2.putText(img, f"{self.cam.name or self.machine_id}  {self.fps:.1f} fps", (8, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        for u in snap:
            y += 22
            who = self.gallery.label(u["user_id"]) or u["user_id"][:8]
            if u["resting"]:
                state = f"RESTING {max(0, u['rest_until'] - now):.0f}s left"
            elif u["seconds_unseen"] >= 1:
                state = f"away {u['seconds_unseen']:.0f}s, released in {max(0, u['leaves_at'] - now):.0f}s"
            else:
                state = "present"
            cv2.putText(img, f"{who}: {state}  (rests {u['rests_used']}/{self.presence.max_rests})",
                        (8, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2)
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 75])
        if ok:
            self._jpeg, self._jpeg_seq = buf.tobytes(), self._jpeg_seq + 1

    def latest_jpeg(self) -> tuple[int, bytes | None]:
        return self._jpeg_seq, self._jpeg
