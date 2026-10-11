"""InsightFace (RetinaFace detector + ArcFace recognizer) running on the CPU."""
from __future__ import annotations

import logging
import threading
import warnings
from dataclasses import dataclass

import cv2
import numpy as np

from .config import settings

log = logging.getLogger(__name__)
# insightface's face_align calls a scikit-image API that warns on every face (harmless; skimage is pinned < 2.2)
warnings.filterwarnings("ignore", category=FutureWarning, module="insightface")


@dataclass
class Face:
    bbox: np.ndarray        # x1, y1, x2, y2
    kps: np.ndarray         # 5x2: eye (image-left), eye (image-right), nose, mouth L, mouth R
    det_score: float
    embedding: np.ndarray   # 512-d, L2 normalised

    @property
    def width(self) -> float:
        return float(self.bbox[2] - self.bbox[0])

    @property
    def area(self) -> float:
        return float((self.bbox[2] - self.bbox[0]) * (self.bbox[3] - self.bbox[1]))

    def head_pose(self) -> tuple[float, float]:
        """Rough head rotation from the 5 landmarks, as (yaw, pitch) ratios.

        yaw   ~ 0 facing the camera; > 0 when the person turns to THEIR left
              (nose moves toward the image's right side in an un-mirrored frame).
        pitch ~ 0.5-0.85 looking straight (varies per face); smaller when looking up, larger looking down.
        These are compared against the person's own neutral pose during enrollment,
        so the absolute values do not have to be calibrated.

        Measured along the face's own eye axis, so tilting the head sideways doesn't register
        as a turn.
        """
        le, re, nose, lm, rm = self.kps
        eye_mid = (le + re) / 2
        mouth_mid = (lm + rm) / 2
        axis = re - le
        eye_dist = max(float(np.linalg.norm(axis)), 1e-3)
        ux = axis / eye_dist                  # along the eyes
        uy = np.array([-ux[1], ux[0]])        # down the face
        v = nose - eye_mid
        yaw = float(v @ ux) / eye_dist
        pitch = float(v @ uy) / max(float((mouth_mid - eye_mid) @ uy), 1e-3)
        return yaw, pitch



def sharpness(img: np.ndarray, face: Face) -> float:
    """Variance of the Laplacian over the face crop; low = blurry."""
    x1, y1, x2, y2 = face.bbox.astype(int)
    h, w = img.shape[:2]
    crop = img[max(0, y1):min(h, y2), max(0, x1):min(w, x2)]
    if crop.size == 0:
        return 0.0
    gray = cv2.cvtColor(cv2.resize(crop, (112, 112)), cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


class FaceEngine:
    """Thread-safe wrapper; one model instance is shared by every camera + enrollment."""

    _instance: "FaceEngine | None" = None
    _instance_lock = threading.Lock()

    def __init__(self, model_name: str = settings.model_name, det_size: int = settings.det_size):
        from insightface.app import FaceAnalysis  # heavy import, keep it lazy

        log.info("loading InsightFace model %s (first run downloads it to ~/.insightface)", model_name)
        import onnxruntime as ort

        sess_options = ort.SessionOptions()
        if settings.ort_threads > 0:
            sess_options.intra_op_num_threads = settings.ort_threads
        self._app = FaceAnalysis(
            name=model_name,
            allowed_modules=["detection", "recognition"],
            providers=["CPUExecutionProvider"],
            sess_options=sess_options,
        )
        self._app.prepare(ctx_id=-1, det_size=(det_size, det_size))
        self._lock = threading.Lock()

    @classmethod
    def shared(cls) -> "FaceEngine":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def detect(self, img: np.ndarray, min_face_px: int = settings.min_face_px) -> list[Face]:
        with self._lock:
            raw = self._app.get(img)
        faces = [
            Face(bbox=f.bbox, kps=f.kps, det_score=float(f.det_score), embedding=f.normed_embedding)
            for f in raw
        ]
        return [f for f in faces if f.width >= min_face_px]

    def embed_lowres(self, img: np.ndarray, face: Face, face_px: int) -> np.ndarray:
        """Embedding of `face` as it would look `face_px` wide, i.e. seen from across the room.

        Enrollment happens up close, but the machine camera sees people far away; storing these
        degraded embeddings too makes distant faces match much better.
        """
        from insightface.app.common import Face as IFace

        scale = min(1.0, face_px / max(face.width, 1.0))
        h, w = img.shape[:2]
        small = cv2.resize(img, (max(1, int(w * scale)), max(1, int(h * scale))), interpolation=cv2.INTER_AREA)
        blurred = cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)
        with self._lock:
            emb = self._app.models["recognition"].get(blurred, IFace(kps=face.kps))
        return (emb / np.linalg.norm(emb)).astype(np.float32)
