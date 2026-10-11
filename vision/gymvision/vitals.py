"""Heart rate during shoulder-press sets, via Presage's contactless rPPG API.

Talks to the Presage Physiology REST API directly with httpx rather than the official
`presage_technologies` pip package: that package hard-imports `presage_physiology_preprocessing`,
which hard-imports the legacy `mediapipe.python.solutions` API - not present in the slim
`mediapipe` build this project already pins for pose estimation, so the import crashes
before any of our code runs. The HTTP calls below are reverse-engineered from that
package's source (upload-url -> S3 multipart PUT -> complete -> poll retrieve-data) and
skip its optional local preprocessing step, since we already hand it a tight face crop.

Presage bills by seconds of submitted footage (1 credit = 30s on the free tier), so capture
only runs while `SetTracker` has an active set (i.e. someone is mid-rep on this machine) and
is further capped by PRESAGE_BUDGET_S across the whole process - deliberately conservative
so a long demo day can't blow through the account's credits.

Readings are a wellness estimate, not a medical measurement (also Presage's own disclaimer):
rPPG accuracy depends on steady lighting and a mostly-still face, neither guaranteed on a gym
floor, and results lag the actual rep by however long a ~15s clip takes to upload and process.
"""
from __future__ import annotations

import logging
import os
import tempfile
import threading
import time
from collections import deque
from pathlib import Path

import cv2
import httpx
import numpy as np

from .config import settings
from .events import EventSink, make_event

log = logging.getLogger(__name__)

MIN_FRAMES = 30          # skip near-empty windows (e.g. a set that ended almost immediately)
UPLOAD_CHUNK = 5 * 1024 * 1024
POLL_INTERVAL_S = 1.5
POLL_TIMEOUT_S = 45.0


class _Budget:
    """Process-wide cap on seconds of footage submitted, shared by every camera (one API key)."""

    def __init__(self, limit_s: float):
        self.limit_s = limit_s
        self._used_s = 0.0
        self._lock = threading.Lock()
        self._warned = False

    def reserve(self, seconds: float) -> bool:
        with self._lock:
            if self._used_s + seconds > self.limit_s:
                if not self._warned:
                    log.warning("Presage budget exhausted (%.0fs / %.0fs) - heart rate tracking paused "
                                "until the process restarts or PRESAGE_BUDGET_S is raised",
                                self._used_s, self.limit_s)
                    self._warned = True
                return False
            self._used_s += seconds
            return True

    def status(self) -> tuple[float, float]:
        with self._lock:
            return self._used_s, self.limit_s


_budget = _Budget(settings.presage_budget_s)


def _extract_series(value) -> list[float]:
    """Pull plain numbers out of a retrieve-data metric, whatever shape it comes back as:
    a bare number, a list of numbers, or a list of {"value"|"hr"|"bpm": ...} / [t, v] pairs."""
    if value is None:
        return []
    if isinstance(value, (int, float)):
        return [float(value)]
    if isinstance(value, dict):
        value = value.get("values") or value.get("data") or list(value.values())
    nums: list[float] = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, (int, float)):
                nums.append(float(item))
            elif isinstance(item, dict):
                v = item.get("value", item.get("hr", item.get("bpm", item.get("rr"))))
                if isinstance(v, (int, float)):
                    nums.append(float(v))
            elif isinstance(item, (list, tuple)) and len(item) == 2 and isinstance(item[1], (int, float)):
                nums.append(float(item[1]))
    return nums


class PresageClient:
    """Minimal client for the bits of the Presage Physiology API we use."""

    def __init__(self, api_key: str, base_url: str = settings.presage_base_url):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._headers = {"x-api-key": api_key}

    def queue_hr_rr(self, video_path: Path, client: httpx.Client) -> str | None:
        file_size = video_path.stat().st_size
        r = client.post(f"{self.base_url}/v1/upload-url", headers=self._headers,
                        json={"file_size": file_size, "hr_br": {"to_process": True}})
        if r.status_code == 401:
            log.error("Presage: unauthorized on upload-url - check PRESAGE_API_KEY")
            return None
        if r.status_code >= 400:
            log.error("Presage: upload-url request failed (%s): %s", r.status_code, r.text[:500])
            return None
        body = r.json()
        vid_id, upload_id, urls = body["id"], body["upload_id"], body["urls"]

        parts = []
        with video_path.open("rb") as fh:
            for num, url in enumerate(urls, start=1):
                chunk = fh.read(UPLOAD_CHUNK)
                put = client.put(url, content=chunk)
                if put.status_code >= 400:
                    log.error("Presage: part %d upload failed (%s): %s", num, put.status_code, put.text[:500])
                    return None
                parts.append({"ETag": put.headers["ETag"], "PartNumber": num})

        complete = client.post(f"{self.base_url}/v1/complete", headers=self._headers,
                               json={"id": vid_id, "upload_id": upload_id, "parts": parts})
        if complete.status_code >= 400:
            log.error("Presage: complete request failed (%s): %s", complete.status_code, complete.text[:500])
            return None
        return vid_id

    def retrieve(self, vid_id: str, client: httpx.Client, timeout_s: float = POLL_TIMEOUT_S) -> dict | None:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            r = client.post(f"{self.base_url}/retrieve-data", headers=self._headers,
                            json={"id": vid_id, "reshape": False})
            if r.status_code == 200:
                return r.json()
            if r.status_code == 401:
                log.error("Presage: unauthorized - check PRESAGE_API_KEY")
                return None
            time.sleep(POLL_INTERVAL_S)  # 201 = still processing; anything else, just retry
        log.warning("Presage: timed out waiting for result (id=%s)", vid_id)
        return None


class VitalsTracker:
    """One per exercise camera. Feed it face crops while a set is active; it emits
    `vitals_update` events on the given sink once a batch finishes processing."""

    def __init__(self, machine_id: str, exercise: str, sink: EventSink):
        self.machine_id = machine_id
        self.exercise = exercise
        self.sink = sink
        self._frames: deque[np.ndarray] = deque()
        self._window_start: float | None = None
        self._window_user_id: str | None = None
        self._lock = threading.Lock()
        self.enabled = bool(settings.presage_api_key)
        self._client = PresageClient(settings.presage_api_key) if self.enabled else None
        self.latest: dict | None = None  # {"hr", "rr", "ts"} from the most recent reading - for the debug overlay
        if not self.enabled:
            log.warning("PRESAGE_API_KEY not set - heart rate tracking disabled for machine %s", machine_id)

    @property
    def budget_exhausted(self) -> bool:
        used, limit = _budget.status()
        return used >= limit

    def add_frame(self, crop: np.ndarray, now: float, user_id: str | None) -> None:
        """Call only while a set is actively in progress (see worker._feed_vitals) -
        this is the credit-conservation gate, not just a convenience check."""
        if not self.enabled or crop.size == 0 or user_id is None:
            return
        full = False
        with self._lock:
            if self._window_start is None:
                self._window_start, self._window_user_id = now, user_id
            self._frames.append(crop)
            full = now - self._window_start >= settings.vitals_window_s
        if full:
            self.flush(now)

    def flush(self, now: float) -> None:
        """Submit whatever's buffered so far. Safe to call with nothing buffered."""
        with self._lock:
            frames, start, user_id = list(self._frames), self._window_start, self._window_user_id
            self._frames.clear()
            self._window_start = self._window_user_id = None
        if not self.enabled or len(frames) < MIN_FRAMES or start is None:
            return
        window_s = max(1.0, now - start)
        fps = len(frames) / window_s  # actual observed capture rate, not a guess - Presage requires >10fps
        if fps <= 10.0:
            log.warning("machine %s: skipping vitals clip, only %.1f fps captured (Presage requires >10fps)",
                       self.machine_id, fps)
            return
        if not _budget.reserve(window_s):
            return
        threading.Thread(target=self._submit, args=(frames, start, now, user_id, fps),
                         name=f"vitals:{self.machine_id}", daemon=True).start()

    def _submit(self, frames: list[np.ndarray], start: float, end: float, user_id: str, fps: float) -> None:
        path = self._write_clip(frames, fps)
        try:
            with httpx.Client(timeout=15.0) as client:
                vid_id = self._client.queue_hr_rr(path, client)
                if vid_id is None:
                    return
                result = self._client.retrieve(vid_id, client)
            if not result:
                return
            hrs = _extract_series(result.get("hr"))
            rrs = _extract_series(result.get("rr"))
            if not hrs:
                log.info("Presage: no hr in response for machine %s (keys: %s) - "
                         "response shape may differ from what this integration expects",
                         self.machine_id, list(result.keys()))
                return
            event = make_event("vitals_update", self.machine_id, end, user_id=user_id, exercise=self.exercise,
                               hr=round(sum(hrs) / len(hrs), 1), peak_hr=round(max(hrs), 1),
                               rr=round(sum(rrs) / len(rrs), 1) if rrs else None,
                               window_start=round(start, 3), window_end=round(end, 3))
            self.sink.emit([event])
            self.latest = {"hr": event["hr"], "rr": event["rr"], "ts": end}
            used, limit = _budget.status()
            log.info("machine %s: heart rate %.0f bpm (budget %.0fs/%.0fs used)",
                     self.machine_id, event["hr"], used, limit)
        except Exception:
            log.exception("machine %s: vitals processing failed", self.machine_id)
        finally:
            path.unlink(missing_ok=True)

    def _write_clip(self, frames: list[np.ndarray], fps: float) -> Path:
        size = (frames[0].shape[1], frames[0].shape[0])
        fd, name = tempfile.mkstemp(suffix=".mp4", prefix="vitals_")
        os.close(fd)
        path = Path(name)
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, size)
        try:
            for frame in frames:
                writer.write(frame)
        finally:
            writer.release()
        return path
