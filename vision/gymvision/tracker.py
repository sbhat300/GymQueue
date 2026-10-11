"""Part 7: face tracking + presence/rest tracking with grace periods.

FaceTracker      follows faces frame-to-frame (IoU) and votes on identity, so a user
                 stays recognised for a while when they turn away mid-rep.
PresenceTracker  per machine: who is confirmed present, when they left, rests.
                 Pure logic with an explicit `now`, so it is unit-testable.

Events emitted (sent to the backend by events.py):
    user_arrived   recognised user confirmed at the machine (ARRIVE_HITS in ARRIVE_WINDOW_S)
    user_left      user not seen for AWAY_GRACE_S (rest time does not count)
    rest_started   backend approved a rest (via POST /machines/{id}/rest)
    rest_ended     user came back during their rest
    rest_expired   rest time is up and the user is still away (grace starts now)
    unknown_face   an unregistered face is persistently at the machine
"""
from __future__ import annotations

import itertools
from typing import Callable
from collections import deque
from dataclasses import dataclass, field

import numpy as np

from .config import settings
from .engine import Face
from .events import make_event
from .gallery import Match

UNKNOWN = "__unknown__"


# --------------------------------------------------------------------------- face tracking
def iou(a: np.ndarray, b: np.ndarray) -> float:
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return float(inter / union) if union > 0 else 0.0


@dataclass
class Track:
    id: int
    bbox: np.ndarray
    last_seen: float
    votes: dict[str, float] = field(default_factory=dict)
    last_score: float = 0.0
    emb_sum: np.ndarray | None = None   # quality-weighted running sum of this face's embeddings
    frames: int = 0

    @property
    def identity(self) -> str:
        return max(self.votes.items(), key=lambda kv: kv[1])[0] if self.votes else UNKNOWN

    @property
    def embedding(self) -> np.ndarray:
        return self.emb_sum / np.linalg.norm(self.emb_sum)


class FaceTracker:
    """Follows faces between frames and recognises the *track*, not single frames.

    Far-away faces give noisy embeddings frame to frame; averaging them over the track
    (weighted by face size and detector confidence) is much more stable than any one frame.
    """
    VOTE_DECAY = 0.85
    UNKNOWN_VOTE = 0.3
    IOU_MIN = 0.25
    TRACK_TTL_S = 4.0
    EMB_DECAY = 0.85        # older frames fade out of the average
    SWAP_SIM = 0.2          # new face looks nothing like the track -> someone else stepped in
    FULL_QUALITY_PX = 112   # faces this wide or larger count fully in the average

    def __init__(self):
        self.tracks: list[Track] = []
        self._ids = itertools.count(1)

    def update(self, faces: list[Face], now: float, matcher: Callable[[np.ndarray], Match]) -> list[Track]:
        """Returns the tracks that were seen in this frame."""
        pairs = sorted(
            ((iou(t.bbox, f.bbox), ti, fi) for ti, t in enumerate(self.tracks) for fi, f in enumerate(faces)),
            reverse=True,
        )
        used_t, used_f, assigned = set(), set(), {}
        for score, ti, fi in pairs:
            if score < self.IOU_MIN:
                break
            if ti in used_t or fi in used_f:
                continue
            used_t.add(ti), used_f.add(fi)
            assigned[fi] = self.tracks[ti]
        for fi, f in enumerate(faces):
            if fi not in assigned:
                t = Track(next(self._ids), f.bbox, now)
                self.tracks.append(t)
                assigned[fi] = t

        seen = []
        for fi, f in enumerate(faces):
            t = assigned[fi]
            if t.emb_sum is not None and t.frames >= 3 and float(f.embedding @ t.embedding) < self.SWAP_SIM:
                t.emb_sum, t.votes, t.frames = None, {}, 0
            weight = f.det_score * min(1.0, f.width / self.FULL_QUALITY_PX)
            t.emb_sum = weight * f.embedding if t.emb_sum is None else self.EMB_DECAY * t.emb_sum + weight * f.embedding
            t.frames += 1
            m = matcher(t.embedding)
            t.bbox, t.last_seen, t.last_score = f.bbox, now, m.score
            for k in t.votes:
                t.votes[k] *= self.VOTE_DECAY
            key = m.user_id or UNKNOWN
            t.votes[key] = t.votes.get(key, 0.0) + (m.score if m.user_id else self.UNKNOWN_VOTE)
            seen.append(t)
        self.tracks = [t for t in self.tracks if now - t.last_seen <= self.TRACK_TTL_S]
        return seen


# --------------------------------------------------------------------------- presence
# A rest only ends early if the user actually walked off (unseen this long) and came back;
# otherwise someone tapping "rest" while still at the machine would cancel it instantly.
REST_LEAVE_S = 3.0


class RestLimitError(Exception):
    pass


@dataclass
class UserPresence:
    user_id: str
    first_seen: float
    last_seen: float
    hits: deque = field(default_factory=lambda: deque(maxlen=64))
    confirmed: bool = False
    rests_used: int = 0
    rest_until: float | None = None
    rest_expired_sent: bool = False
    left_during_rest: bool = False   # walked out of view after starting the rest

    @property
    def resting(self) -> bool:
        return self.rest_until is not None


class PresenceTracker:
    def __init__(self, machine_id: str, *, arrive_hits=settings.arrive_hits,
                 arrive_window_s=settings.arrive_window_s, away_grace_s=settings.away_grace_s,
                 max_rests=settings.max_rests, unknown_cooldown_s=settings.unknown_cooldown_s):
        self.machine_id = machine_id
        self.arrive_hits = arrive_hits
        self.arrive_window_s = arrive_window_s
        self.away_grace_s = away_grace_s
        self.max_rests = max_rests
        self.unknown_cooldown_s = unknown_cooldown_s
        self.rest_leave_s = REST_LEAVE_S
        self.users: dict[str, UserPresence] = {}
        self._unknown_hits: deque = deque(maxlen=64)
        self._unknown_last_sent = -1e9

    def _ev(self, kind, now, **data):
        return make_event(kind, self.machine_id, now, **data)

    def deadline(self, p: UserPresence) -> float:
        """When this user is considered gone if they are not seen again."""
        base = max(p.last_seen, p.rest_until or 0.0)
        return base + self.away_grace_s

    # ---- main entry point, called once per processed frame ----
    def observe(self, now: float, seen_users: dict[str, float], unknown_faces: int = 0) -> list[dict]:
        """seen_users: user_id -> match score for every recognised face in this frame."""
        events: list[dict] = []

        for uid, score in seen_users.items():
            p = self.users.get(uid)
            if p is None:
                p = self.users[uid] = UserPresence(uid, now, now)
            if p.resting and now - p.last_seen >= self.rest_leave_s:
                p.left_during_rest = True
            p.last_seen = now
            p.hits.append(now)
            if not p.confirmed:
                recent = sum(1 for t in p.hits if now - t <= self.arrive_window_s)
                if recent >= self.arrive_hits:
                    p.confirmed = True
                    events.append(self._ev("user_arrived", now, user_id=uid, confidence=round(score, 3)))
            elif p.resting and (p.left_during_rest or now >= p.rest_until):
                reason = "returned" if p.left_during_rest else "expired"
                p.rest_until = None
                events.append(self._ev("rest_ended", now, user_id=uid, reason=reason,
                                       rests_used=p.rests_used))

        for uid, p in list(self.users.items()):
            if uid in seen_users:
                continue
            if not p.confirmed:
                if now - p.last_seen > self.arrive_window_s:  # walked past, never confirmed
                    del self.users[uid]
                continue
            if p.resting and now >= p.rest_until and not p.rest_expired_sent:
                p.rest_expired_sent = True
                events.append(self._ev("rest_expired", now, user_id=uid, rests_used=p.rests_used,
                                       grace_until=round(self.deadline(p), 3)))
            if now >= self.deadline(p):
                events.append(self._ev("user_left", now, user_id=uid, last_seen=round(p.last_seen, 3),
                                       was_resting=p.resting))
                del self.users[uid]

        if unknown_faces:
            self._unknown_hits.append(now)
            recent = sum(1 for t in self._unknown_hits if now - t <= self.arrive_window_s)
            if recent >= self.arrive_hits and now - self._unknown_last_sent >= self.unknown_cooldown_s:
                self._unknown_last_sent = now
                events.append(self._ev("unknown_face", now, count=unknown_faces))
        return events

    # ---- commands from the backend ----
    def start_rest(self, user_id: str, seconds: float, now: float) -> dict:
        p = self.users.get(user_id)
        if p is None:  # backend is authoritative: accept even if the camera missed them
            p = self.users[user_id] = UserPresence(user_id, now, now, confirmed=True)
        if p.resting:
            raise ValueError("already resting")
        if p.rests_used >= self.max_rests:
            raise RestLimitError(f"rest limit reached ({self.max_rests})")
        p.rests_used += 1
        p.rest_until = now + seconds
        p.rest_expired_sent = False
        p.left_during_rest = False
        return self._ev("rest_started", now, user_id=user_id, rest_until=round(p.rest_until, 3),
                        rests_used=p.rests_used, rests_left=self.max_rests - p.rests_used)

    def end_rest(self, user_id: str, now: float) -> dict | None:
        p = self.users.get(user_id)
        if not p or not p.resting:
            return None
        p.rest_until = None
        p.last_seen = max(p.last_seen, now)  # grace counts from the moment the rest was cancelled
        return self._ev("rest_ended", now, user_id=user_id, reason="cancelled", rests_used=p.rests_used)

    def release(self, user_id: str) -> None:
        """Backend says this user's session is over (e.g. they left the queue)."""
        self.users.pop(user_id, None)

    def shift_time(self, seconds: float) -> None:
        """Camera was offline for `seconds`; don't count that as the user being away."""
        for p in self.users.values():
            p.last_seen += seconds
            if p.rest_until is not None:
                p.rest_until += seconds

    def snapshot(self, now: float) -> list[dict]:
        return [{
            "user_id": p.user_id,
            "last_seen": round(p.last_seen, 3),
            "seconds_unseen": round(max(0.0, now - p.last_seen), 1),
            "resting": p.resting,
            "rest_until": round(p.rest_until, 3) if p.rest_until else None,
            "rests_used": p.rests_used,
            "leaves_at": round(self.deadline(p), 3),
        } for p in self.users.values() if p.confirmed]
