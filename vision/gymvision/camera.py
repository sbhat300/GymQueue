"""Frame sources.

Source strings (used in cameras.json and on the command line):
    esp32:http://192.168.43.50     ESP32-CAM running firmware/esp32cam (polls /capture)
    snapshot:http://host/shot.jpg  any URL that returns a single JPEG per GET
    mjpeg:http://host:81/stream    any MJPEG stream (ESP32 /stream, phone IP-webcam apps)
    webcam:0                       local USB/laptop webcam at 1280x720 (stand-in until the ESP32 arrives)
    webcam:0@1920x1080             same, asking for a specific resolution
    file:path/to/video.mp4         video file, loops forever (for testing)
    serial:/dev/ttyACM0            ESP32 over its USB cable (no Wi-Fi needed); serial:/dev/ttyACM0@921600

A camera can also list several sources, e.g. ["esp32:http://gymcam-x.local", "serial:/dev/ttyACM0"]:
it uses the first that delivers frames and moves to the next if that one goes quiet.

Every source runs a background grabber thread and only keeps the newest frame, so
slow face processing never builds up a backlog of stale frames.
"""
from __future__ import annotations

import logging
import threading
import time

import cv2
import httpx
import numpy as np

log = logging.getLogger(__name__)


class FrameSource:
    def __init__(self, spec: str):
        self.spec = spec
        self._frame: np.ndarray | None = None
        self._frame_ts = 0.0
        self._seq = 0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.connected = False
        self.last_error = ""

    # -- public --
    def start(self) -> "FrameSource":
        self._thread = threading.Thread(target=self._run, name=f"grab:{self.spec}", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()

    def latest(self, after_seq: int = -1) -> tuple[int, float, np.ndarray | None]:
        """Newest (seq, timestamp, frame). Frame is None if nothing newer than after_seq."""
        with self._lock:
            if self._frame is None or self._seq <= after_seq:
                return self._seq, self._frame_ts, None
            return self._seq, self._frame_ts, self._frame

    # -- internals --
    def _publish(self, frame: np.ndarray) -> None:
        with self._lock:
            self._frame = frame
            self._frame_ts = time.time()
            self._seq += 1
        self.connected = True

    def _run(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                self._loop()
                backoff = 1.0
            except Exception as e:  # keep retrying forever; cameras drop off Wi-Fi
                self.connected = False
                self.last_error = str(e)
                log.warning("camera %s error: %s (retry in %.0fs)", self.spec, e, backoff)
                self._stop.wait(backoff)
                backoff = min(backoff * 2, 10.0)

    def _loop(self) -> None:
        raise NotImplementedError


class SnapshotSource(FrameSource):
    """Polls a URL that returns one JPEG per request (ESP32 /capture)."""

    def __init__(self, spec: str, url: str, max_fps: float = 10.0):
        super().__init__(spec)
        self.url = url
        self.min_interval = 1.0 / max_fps

    def _loop(self) -> None:
        with httpx.Client(timeout=5.0) as client:
            while not self._stop.is_set():
                t0 = time.time()
                r = client.get(self.url)
                r.raise_for_status()
                frame = cv2.imdecode(np.frombuffer(r.content, np.uint8), cv2.IMREAD_COLOR)
                if frame is None:
                    raise RuntimeError("response was not a decodable image")
                self._publish(frame)
                self._stop.wait(max(0.0, self.min_interval - (time.time() - t0)))


class OpenCVSource(FrameSource):
    """Webcam index, MJPEG URL or video file, read through cv2.VideoCapture."""

    def __init__(self, spec: str, target: int | str, loop_file: bool = False,
                 size: tuple[int, int] | None = None):
        super().__init__(spec)
        self.target = target
        self.loop_file = loop_file
        self.size = size

    def _loop(self) -> None:
        cap = cv2.VideoCapture(self.target)
        if not cap.isOpened():
            raise RuntimeError(f"could not open {self.target!r}")
        if self.size:
            # webcams default to 640x480, which makes anyone past ~1 m too small to recognise.
            # MJPG keeps the frame rate up at 720p+ (raw YUYV often drops to a few fps).
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.size[0])
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.size[1])
            log.info("camera %s: %dx%d", self.spec, cap.get(cv2.CAP_PROP_FRAME_WIDTH),
                     cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS) if self.loop_file else 0
        try:
            while not self._stop.is_set():
                ok, frame = cap.read()
                if not ok:
                    if self.loop_file:
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        continue
                    raise RuntimeError("stream ended / read failed")
                self._publish(frame)
                if fps and fps > 0:  # play files back at real speed
                    time.sleep(1.0 / fps)
        finally:
            cap.release()


class SerialSource(FrameSource):
    """Frames over the ESP32's USB cable (firmware/esp32cam): send SNAP, read FRAME <n> + n bytes."""

    def __init__(self, spec: str, port: str, baud: int = 921600, max_fps: float = 15.0):
        super().__init__(spec)
        self.port, self.baud = port, baud
        self.min_interval = 1.0 / max_fps

    def _read_header(self, ser) -> int:
        """Skip any log lines until 'FRAME <length>'."""
        for _ in range(50):
            line = ser.readline()
            if not line:
                raise RuntimeError("camera didn't answer over USB (is the firmware flashed and the cable in?)")
            if line.startswith(b"FRAME "):
                return int(line[6:].strip() or 0)
        raise RuntimeError("no frame header from the camera")

    MAX_MISSES = 10  # ~20-40 s of no answers before reopening the port

    def _loop(self) -> None:
        import serial  # pyserial

        ser = serial.Serial()
        ser.port, ser.baudrate, ser.timeout = self.port, self.baud, 4.0
        # Keep both control lines on: on these boards dropping them (pyserial's dtr/rts=False)
        # pulses the reset pin, and the ESP32 would reboot every time we connect.
        ser.dtr = ser.rts = True
        ser.open()
        misses = 0
        try:
            while not self._stop.is_set():
                t0 = time.time()
                try:
                    ser.write(b"SNAP\n")
                    n = self._read_header(ser)
                    if n <= 0:
                        raise RuntimeError("camera couldn't capture a frame")
                    data = ser.read(n)
                    if len(data) != n:
                        raise RuntimeError("frame cut short over USB")
                    frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
                    if frame is None:
                        raise RuntimeError("bad JPEG over USB")
                except RuntimeError as e:
                    # board busy (booting, scanning for Wi-Fi) or out of sync: resync and ask again
                    misses += 1
                    self.last_error = str(e)
                    if misses >= self.MAX_MISSES:
                        raise
                    ser.reset_input_buffer()
                    continue
                misses = 0
                self._publish(frame)
                self._stop.wait(max(0.0, self.min_interval - (time.time() - t0)))
        finally:
            ser.close()


class FallbackSource(FrameSource):
    """Several ways to reach one camera; uses whichever delivers frames, switching after a gap."""

    SWITCH_AFTER_S = 6.0

    def __init__(self, specs: list[str], factory=None):
        super().__init__(" | ".join(specs))
        self.specs = specs
        self.factory = factory or open_source
        self.active_index = 0
        self.active: FrameSource | None = None

    def _loop(self) -> None:
        self.active = self.factory(self.specs[self.active_index]).start()
        seq, last_frame = -1, time.time()
        try:
            while not self._stop.is_set():
                new_seq, _, frame = self.active.latest(seq)
                now = time.time()
                if frame is not None:
                    seq, last_frame = new_seq, now
                    self._publish(frame)
                elif now - last_frame > self.SWITCH_AFTER_S and len(self.specs) > 1:
                    self.last_error = f"{self.active.spec}: {self.active.last_error or 'no frames'}"
                    self.active.stop()
                    self.active_index = (self.active_index + 1) % len(self.specs)
                    log.warning("camera switching to %s (%s)", self.specs[self.active_index], self.last_error)
                    self.active = self.factory(self.specs[self.active_index]).start()
                    seq, last_frame = -1, now
                self.connected = self.active.connected
                self._stop.wait(0.02)
        finally:
            if self.active is not None:
                self.active.stop()


def open_source(spec: str | list[str]) -> FrameSource:
    if isinstance(spec, list):
        return FallbackSource(spec) if len(spec) > 1 else open_source(spec[0])
    kind, _, rest = spec.partition(":")
    if kind == "esp32":
        return SnapshotSource(spec, rest.rstrip("/") + "/capture")
    if kind == "snapshot":
        return SnapshotSource(spec, rest)
    if kind == "mjpeg":
        return OpenCVSource(spec, rest)
    if kind == "webcam":
        index, _, res = rest.partition("@")
        w, _, h = (res or "1280x720").partition("x")
        return OpenCVSource(spec, int(index or 0), size=(int(w), int(h)))
    if kind == "file":
        return OpenCVSource(spec, rest, loop_file=True)
    if kind == "serial":
        port, _, baud = rest.partition("@")
        return SerialSource(spec, port, int(baud or 921600))
    raise ValueError(f"unknown camera source {spec!r} (expected esp32:/snapshot:/mjpeg:/webcam:/file:/serial:)")
