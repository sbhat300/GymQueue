"""Part 2: guided face scan with head rotation.

The user is walked through 5 poses (center, left, right, up, down). For each pose we
keep a few good frames, check that it is still the same person, then store the mean
ArcFace embedding per pose. Several poses make recognition work when the gym camera
sees people from an angle, not just straight on.

Used by both the desktop CLI (scripts/enroll_cli.py) and the HTTP API (server.py),
so a web signup page can stream webcam frames here and just display `message`.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

import numpy as np

from .engine import Face, FaceEngine, sharpness
from .gallery import Gallery
from .store import FaceStore

POSES = ["center", "left", "right", "up", "down"]
INSTRUCTIONS = {
    "center": "Look straight at the camera",
    "left": "Slowly turn your head to your LEFT",
    "right": "Slowly turn your head to your RIGHT",
    "up": "Tilt your head UP a little",
    "down": "Tilt your head DOWN a little",
}
SAMPLES_PER_POSE = 3
FAR_POSES = ("center", "left", "right")  # also stored as "<pose>_far": how the face looks from ~3-4 m
FAR_FACE_PX = 32
MIN_SAMPLE_GAP_S = 0.25      # don't take all samples from near-identical consecutive frames
MIN_ENROLL_FACE_PX = 90
MIN_DET_SCORE = 0.6
MIN_SHARPNESS = 25.0
CENTER_MAX_YAW = 0.20
TURN_MIN_YAW = 0.12          # yaw ratio change vs. the user's own neutral pose (~12 degrees)
TILT_MIN_PITCH = 0.07
TILT_MAX_YAW = 0.20          # up/down steps: how much sideways turn is still tolerated
SAME_PERSON_MIN_SIM = 0.35   # every sample must look like the center samples
DUPLICATE_SIM = 0.55         # finishing is refused if the face already belongs to someone else


@dataclass
class FrameResult:
    accepted: bool
    message: str
    face: Face | None = None
    yaw: float | None = None
    pitch: float | None = None


@dataclass
class EnrollmentSession:
    user_id: str
    label: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: float = field(default_factory=time.time)
    samples: dict[str, list[np.ndarray]] = field(default_factory=lambda: {p: [] for p in POSES})
    far_samples: dict[str, list[np.ndarray]] = field(default_factory=lambda: {p: [] for p in FAR_POSES})
    _baseline: tuple[float, float] | None = None
    _center_yp: list[tuple[float, float]] = field(default_factory=list)
    _last_accept: float = 0.0

    # ---------- progress ----------
    @property
    def step(self) -> str | None:
        for p in POSES:
            if len(self.samples[p]) < SAMPLES_PER_POSE:
                return p
        return None

    @property
    def done(self) -> bool:
        return self.step is None

    @property
    def progress(self) -> float:
        return sum(min(len(v), SAMPLES_PER_POSE) for v in self.samples.values()) / (SAMPLES_PER_POSE * len(POSES))

    def status(self, result: FrameResult | None = None) -> dict:
        out = {
            "session_id": self.id,
            "user_id": self.user_id,
            "step": self.step,
            "steps": POSES,
            "samples": {p: len(v) for p, v in self.samples.items()},
            "samples_per_pose": SAMPLES_PER_POSE,
            "progress": round(self.progress, 3),
            "done": self.done,
            "instruction": INSTRUCTIONS[self.step] if self.step else "All poses captured - finishing up",
        }
        if result:
            out["accepted"] = result.accepted
            out["message"] = result.message
            out["face"] = None if result.face is None else {
                "bbox": [round(float(v), 1) for v in result.face.bbox],
                "yaw": round(result.yaw, 3), "pitch": round(result.pitch, 3),
            }
        return out

    # ---------- per frame ----------
    def add_frame(self, img: np.ndarray, engine: FaceEngine) -> FrameResult:
        step = self.step
        if step is None:
            return FrameResult(False, "Already complete")

        faces = sorted(engine.detect(img, min_face_px=40), key=lambda f: f.area, reverse=True)
        if not faces:
            return FrameResult(False, "No face found - make sure your face is lit and in frame")
        face = faces[0]
        yaw, pitch = face.head_pose()
        res = lambda ok, msg: FrameResult(ok, msg, face, yaw, pitch)  # noqa: E731

        if len(faces) > 1 and faces[1].area > 0.4 * face.area:
            return res(False, "Only one person in frame please")

        if face.width < MIN_ENROLL_FACE_PX:
            return res(False, "Move closer to the camera")
        if face.det_score < MIN_DET_SCORE:
            return res(False, "Face not clear - check lighting")
        if sharpness(img, face) < MIN_SHARPNESS:
            return res(False, "Hold still")

        # pose check
        if step == "center":
            if abs(yaw) > CENTER_MAX_YAW:
                return res(False, "Look straight at the camera")
        else:
            by, bp = self._baseline
            dy, dp = yaw - by, pitch - bp
            ok = {
                "left": dy >= TURN_MIN_YAW,
                "right": dy <= -TURN_MIN_YAW,
                "up": dp <= -TILT_MIN_PITCH and abs(dy) < TILT_MAX_YAW,
                "down": dp >= TILT_MIN_PITCH and abs(dy) < TILT_MAX_YAW,
            }[step]
            if not ok:
                return res(False, INSTRUCTIONS[step])

        # same-person check (stops someone else finishing your scan)
        ref = self._center_mean()
        if ref is not None and float(face.embedding @ ref) < SAME_PERSON_MIN_SIM:
            return res(False, "Face changed - the same person must complete the scan")

        now = time.time()
        if now - self._last_accept < MIN_SAMPLE_GAP_S:
            return res(False, INSTRUCTIONS[step])
        self._last_accept = now
        self.samples[step].append(face.embedding.copy())
        if step in FAR_POSES:
            self.far_samples[step].append(engine.embed_lowres(img, face, FAR_FACE_PX))
        if step == "center":
            self._center_yp.append((yaw, pitch))
            if len(self.samples["center"]) == SAMPLES_PER_POSE:
                self._baseline = tuple(np.mean(self._center_yp, axis=0))
        return res(True, "Got it" if self.step == step else "Pose captured!")

    def _center_mean(self) -> np.ndarray | None:
        c = self.samples["center"]
        if not c:
            return None
        m = np.mean(c, axis=0)
        return m / np.linalg.norm(m)

    # ---------- finish ----------
    def pose_embeddings(self) -> dict[str, np.ndarray]:
        groups = {**self.samples, **{f"{p}_far": v for p, v in self.far_samples.items() if v}}
        out = {}
        for p, vecs in groups.items():
            m = np.mean(vecs, axis=0)
            out[p] = (m / np.linalg.norm(m)).astype(np.float32)
        return out

    def finish(self, store: FaceStore, gallery: Gallery) -> dict:
        if not self.done:
            raise ValueError(f"scan incomplete, still need pose '{self.step}'")
        embs = self.pose_embeddings()
        # refuse if this face is already enrolled under a different account
        for e in embs.values():
            m = gallery.scores(e)
            m.pop(self.user_id, None)
            if m and max(m.values()) >= DUPLICATE_SIM:
                raise PermissionError("This face is already registered to another account")
        store.save_user(self.user_id, embs, label=self.label)
        gallery.reload()
        return {"user_id": self.user_id, "poses": list(embs), "stored": True}
