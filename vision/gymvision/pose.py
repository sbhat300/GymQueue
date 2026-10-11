"""Body pose for rep counting: MediaPipe Pose Landmarker (lite), CPU, ~40 ms per frame."""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import httpx
import numpy as np

from .config import ROOT

log = logging.getLogger(__name__)

MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
             "pose_landmarker_lite/float16/latest/pose_landmarker_lite.task")
MODEL_PATH = ROOT / "data" / "models" / "pose_landmarker_lite.task"

# MediaPipe's 33-point body model
KEYPOINTS = {"nose": 0, "l_shoulder": 11, "r_shoulder": 12, "l_elbow": 13, "r_elbow": 14,
             "l_wrist": 15, "r_wrist": 16, "l_hip": 23, "r_hip": 24}
SKELETON = [("l_shoulder", "r_shoulder"), ("l_shoulder", "l_elbow"), ("l_elbow", "l_wrist"),
            ("r_shoulder", "r_elbow"), ("r_elbow", "r_wrist")]


@dataclass
class Pose:
    points: dict[str, tuple[float, float, float]]  # name -> (x px, y px, visibility 0-1)

    def get(self, name: str, min_visibility: float = 0.5) -> np.ndarray | None:
        x, y, v = self.points[name]
        return np.array([x, y]) if v >= min_visibility else None


def ensure_model(path: Path = MODEL_PATH) -> Path:
    if not path.exists():
        log.info("downloading pose model (~6 MB) to %s", path)
        path.parent.mkdir(parents=True, exist_ok=True)
        r = httpx.get(MODEL_URL, follow_redirects=True, timeout=60)
        r.raise_for_status()
        path.write_bytes(r.content)
    return path


class PoseEstimator:
    """One per camera (VIDEO mode keeps track of the person between frames)."""

    def __init__(self, model_path: Path | None = None):
        from mediapipe.tasks import python as mpt  # heavy import, keep it lazy
        from mediapipe.tasks.python import vision as mpv

        options = mpv.PoseLandmarkerOptions(
            base_options=mpt.BaseOptions(model_asset_path=str(ensure_model(model_path or MODEL_PATH))),
            running_mode=mpv.RunningMode.VIDEO,
            num_poses=1,
        )
        self._landmarker = mpv.PoseLandmarker.create_from_options(options)
        self._lock = threading.Lock()
        self._last_ms = 0

    def detect(self, img: np.ndarray) -> Pose | None:
        import mediapipe as mp

        h, w = img.shape[:2]
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        with self._lock:
            ms = max(int(time.monotonic() * 1000), self._last_ms + 1)  # VIDEO mode needs increasing timestamps
            self._last_ms = ms
            result = self._landmarker.detect_for_video(image, ms)
        if not result.pose_landmarks:
            return None
        lms = result.pose_landmarks[0]
        return Pose({name: (lms[i].x * w, lms[i].y * h, lms[i].visibility) for name, i in KEYPOINTS.items()})

    def close(self) -> None:
        with self._lock:
            self._landmarker.close()
