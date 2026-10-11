"""Rep counting from body pose, and grouping reps into sets.

Shoulder press, per frame, from whichever arms are visible:
    elbow angle   shoulder-elbow-wrist; ~90 deg at the bottom, ~170 deg locked out overhead
    wrist height  how far the wrists are above the shoulders, in shoulder widths
    down = elbows bent and hands near shoulder height; up = arms straight with hands well overhead
A rep is counted when the arms reach "up" after having been "down" (each held 2 frames, so a
single bad pose estimate can't count or break a rep).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .pose import Pose

EXERCISE_LABELS = {"shoulder_press": "Shoulder press"}


def _angle(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> float:
    """Angle at b, in degrees."""
    v1, v2 = a - b, c - b
    cos = float(v1 @ v2 / (np.linalg.norm(v1) * np.linalg.norm(v2) + 1e-6))
    return float(np.degrees(np.arccos(np.clip(cos, -1.0, 1.0))))


@dataclass
class PressMetrics:
    elbow_angle: float | None   # degrees, mean over arms with a visible wrist; None if no wrist in view
    wrist_height: float | None  # hands above shoulders, in shoulder widths
    elbow_height: float         # elbows above shoulders, in shoulder widths (always in view)


@dataclass
class ShoulderPressCounter:
    up_elbow_deg: float = 150.0
    down_elbow_deg: float = 115.0
    # hands' height above the shoulders, in shoulder widths: ~0.4-0.9 at the bottom (ear height),
    # ~1.5-1.7 locked out overhead
    up_wrist_height: float = 1.2
    down_wrist_height: float = 0.9
    # Close to a webcam the hands leave the top of the frame at lockout. Elbows stay in view:
    # about level with the shoulders at the bottom, well above them at the top.
    up_elbow_height: float = 0.6
    down_elbow_height: float = 0.25
    confirm_frames: int = 2

    reps: int = 0
    phase: str = "start"              # start -> down -> up -> down -> ...
    _candidate: str = ""
    _candidate_frames: int = 0
    last_metrics: PressMetrics | None = None

    def metrics(self, pose: Pose) -> PressMetrics | None:
        ls, rs = pose.get("l_shoulder"), pose.get("r_shoulder")
        if ls is None or rs is None:
            return None
        width = max(float(np.linalg.norm(ls - rs)), 1.0)
        angles, wrist_h, elbow_h = [], [], []
        for shoulder, side in ((ls, "l"), (rs, "r")):
            elbow = pose.get(f"{side}_elbow", 0.3)
            if elbow is None:
                continue
            elbow_h.append((shoulder[1] - elbow[1]) / width)  # image y points down
            wrist = pose.get(f"{side}_wrist", 0.3)
            if wrist is not None:
                angles.append(_angle(shoulder, elbow, wrist))
                wrist_h.append((shoulder[1] - wrist[1]) / width)
        if not elbow_h:
            return None
        return PressMetrics(float(np.mean(angles)) if angles else None,
                            float(np.mean(wrist_h)) if wrist_h else None,
                            float(np.mean(elbow_h)))

    def classify(self, m: PressMetrics) -> str:
        if m.elbow_angle is not None:
            if m.elbow_angle >= self.up_elbow_deg and m.wrist_height >= self.up_wrist_height:
                return "up"
            if m.elbow_angle <= self.down_elbow_deg and m.wrist_height <= self.down_wrist_height:
                return "down"
        # hands out of frame (or arm straight but hands mis-placed): go by the elbows
        if m.elbow_height >= self.up_elbow_height and (m.elbow_angle is None or m.elbow_angle >= 130):
            return "up"
        if m.elbow_height <= self.down_elbow_height and (m.elbow_angle is None or m.elbow_angle <= 125):
            return "down"
        return "mid"

    def update(self, pose: Pose | None) -> bool:
        """Feed one frame; returns True when this frame completes a rep."""
        m = self.metrics(pose) if pose is not None else None
        self.last_metrics = m
        if m is None:
            return False
        state = self.classify(m)
        if state == "mid":
            return False
        if state != self._candidate:
            self._candidate, self._candidate_frames = state, 0
        self._candidate_frames += 1
        if self._candidate_frames < self.confirm_frames or state == self.phase:
            return False
        if state == "down":
            self.phase = "down"
            return False
        if self.phase == "down":  # down -> up: one rep
            self.phase = "up"
            self.reps += 1
            return True
        self.phase = "up"  # started with arms already up: wait for a full down-up
        return False

    def reset(self) -> None:
        self.reps, self.phase, self._candidate, self._candidate_frames = 0, "start", "", 0


@dataclass
class SetTracker:
    """Reps by one person become a set; the set ends after `idle_s` without a rep."""
    exercise: str
    idle_s: float = 15.0
    user_id: str | None = None
    reps: int = 0
    started_at: float = 0.0
    last_rep_at: float = 0.0
    counter: ShoulderPressCounter = field(default_factory=ShoulderPressCounter)

    def add_rep(self, user_id: str | None, now: float) -> dict | None:
        """Returns a finished set if a different person started repping."""
        if user_id is None:
            user_id = self.user_id  # face hidden for a moment (arms overhead) - still their set
        finished = self.finish() if self.reps and user_id != self.user_id else None
        if self.reps == 0:
            self.user_id, self.started_at = user_id, now
        self.reps += 1
        self.last_rep_at = now
        return finished

    def expire(self, now: float) -> dict | None:
        if self.reps and now - self.last_rep_at >= self.idle_s:
            return self.finish()
        return None

    def finish(self) -> dict | None:
        if not self.reps:
            return None
        done = {"user_id": self.user_id, "exercise": self.exercise, "reps": self.reps,
                "started_at": round(self.started_at, 3), "ended_at": round(self.last_rep_at, 3)}
        self.user_id, self.reps = None, 0
        self.counter.reset()
        return done
