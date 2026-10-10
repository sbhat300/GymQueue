"""Delivers presence events to the GymQueue backend over authenticated HTTP.

POST {BACKEND_URL}{BACKEND_EVENTS_PATH}
Authorization: Bearer {BACKEND_API_KEY}
Body: {"events": [ {...}, ... ]}

Sending happens on a background thread with retries, so a slow or offline backend
never stalls the camera loop. If BACKEND_URL is empty, events are only logged.
"""
from __future__ import annotations

import json
import logging
import queue
import threading
import time
import uuid
from collections import deque

import httpx

from .config import settings

log = logging.getLogger("events")


def make_event(kind: str, machine_id: str, now: float | None = None, **data) -> dict:
    now = time.time() if now is None else now
    return {"id": uuid.uuid4().hex, "type": kind, "machine_id": machine_id,
            "ts": round(now, 3), "at": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now)) + "Z", **data}


class EventSink:
    def __init__(self, url: str = settings.backend_url, path: str = settings.backend_events_path,
                 api_key: str = settings.backend_api_key):
        self.endpoint = f"{url}{path}" if url else ""
        self.headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self.recent: deque[dict] = deque(maxlen=200)
        self.failed = 0
        self._q: queue.Queue[list[dict]] = queue.Queue(maxsize=1000)
        threading.Thread(target=self._run, name="event-sink", daemon=True).start()

    def emit(self, events: list[dict]) -> None:
        if not events:
            return
        for e in events:
            self.recent.append(e)
            if e["type"] != "heartbeat":
                log.info("%s %s", e["type"], json.dumps({k: v for k, v in e.items() if k not in ("id", "type", "at")}))
        if self.endpoint:
            try:
                self._q.put_nowait(events)
            except queue.Full:
                self.failed += len(events)
                log.error("event queue full, dropping %d events", len(events))

    def _run(self) -> None:
        with httpx.Client(timeout=5.0, headers=self.headers) as client:
            while True:
                batch = self._q.get()
                # coalesce whatever else is waiting into one request
                while len(batch) < 100:
                    try:
                        batch += self._q.get_nowait()
                    except queue.Empty:
                        break
                for attempt in range(4):
                    try:
                        r = client.post(self.endpoint, json={"events": batch})
                        if r.status_code < 500:
                            if r.status_code >= 400:
                                log.error("backend rejected events: %s %s", r.status_code, r.text[:200])
                            break
                        raise httpx.HTTPStatusError(str(r.status_code), request=r.request, response=r)
                    except httpx.HTTPError as e:
                        log.warning("backend unreachable (%s), retry %d", e, attempt + 1)
                        time.sleep(0.5 * 2 ** attempt)
                else:
                    self.failed += len(batch)
                    log.error("gave up delivering %d events", len(batch))
