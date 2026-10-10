import numpy as np
import pytest

from gymvision.gallery import Match
from gymvision.tracker import UNKNOWN, FaceTracker, PresenceTracker, RestLimitError


def types(events):
    return [e["type"] for e in events]


def make(**kw):
    opts = dict(arrive_hits=3, arrive_window_s=4.0, away_grace_s=30.0, max_rests=6, unknown_cooldown_s=30.0)
    opts.update(kw)
    return PresenceTracker("bench-1", **opts)


def arrive(p, uid="u1", t0=0.0):
    evs = []
    for i in range(3):
        evs += p.observe(t0 + i, {uid: 0.7})
    return evs


def test_arrival_needs_several_sightings():
    p = make()
    assert p.observe(0, {"u1": 0.7}) == []
    assert p.observe(1, {"u1": 0.7}) == []
    evs = p.observe(2, {"u1": 0.7})
    assert types(evs) == ["user_arrived"]
    assert evs[0]["user_id"] == "u1" and evs[0]["machine_id"] == "bench-1"
    assert p.observe(3, {"u1": 0.7}) == []  # only once


def test_passerby_is_never_reported():
    p = make()
    p.observe(0, {"u1": 0.7})
    assert p.observe(10, {}) == []
    assert "u1" not in p.users


def test_leaves_after_grace_period():
    p = make()
    arrive(p)  # last seen at t=2
    assert p.observe(20, {}) == []
    assert p.observe(31.9, {}) == []
    evs = p.observe(32.0, {})
    assert types(evs) == ["user_left"]
    assert evs[0]["last_seen"] == 2
    assert p.users == {}


def test_coming_back_within_grace_resets_timer():
    p = make()
    arrive(p)
    p.observe(25, {"u1": 0.7})
    assert p.observe(50, {}) == []
    assert types(p.observe(55, {})) == ["user_left"]


def test_rest_suspends_absence_then_grace_after_rest():
    p = make()
    arrive(p)
    ev = p.start_rest("u1", 120, now=3)
    assert ev["type"] == "rest_started" and ev["rests_left"] == 5
    assert p.observe(100, {}) == []                       # long gone, but resting
    assert types(p.observe(123, {})) == ["rest_expired"]  # rest over, grace begins
    assert p.observe(150, {}) == []
    assert types(p.observe(153, {})) == ["user_left"]     # rest_until (123) + 30


def test_return_during_rest_ends_it():
    p = make()
    arrive(p)
    p.start_rest("u1", 120, now=3)
    evs = p.observe(60, {"u1": 0.7})
    assert types(evs) == ["rest_ended"] and evs[0]["reason"] == "returned"
    assert not p.users["u1"].resting
    assert types(p.observe(90, {})) == ["user_left"]


def test_rest_not_cancelled_while_still_walking_away():
    p = make()
    arrive(p)
    p.start_rest("u1", 60, now=3)
    assert p.observe(3.5, {"u1": 0.7}) == []   # still in view right after tapping "rest"
    assert p.observe(4.5, {"u1": 0.7}) == []
    assert p.users["u1"].resting
    assert types(p.observe(20, {"u1": 0.7})) == ["rest_ended"]  # gone 15s, then back


def test_rest_that_never_leaves_view_just_expires():
    p = make()
    arrive(p)
    p.start_rest("u1", 10, now=3)
    for t in range(4, 13):
        assert p.observe(t, {"u1": 0.7}) == []
    evs = p.observe(13, {"u1": 0.7})
    assert types(evs) == ["rest_ended"] and evs[0]["reason"] == "expired"


def test_rest_limit():
    p = make(max_rests=6)
    arrive(p)
    t = 3
    for _ in range(6):
        p.start_rest("u1", 10, now=t)
        p.observe(t + 5, {"u1": 0.7})  # walks off, comes back, rest ends
        t += 6
    with pytest.raises(RestLimitError):
        p.start_rest("u1", 10, now=t)


def test_cannot_double_rest():
    p = make()
    arrive(p)
    p.start_rest("u1", 10, now=3)
    with pytest.raises(ValueError):
        p.start_rest("u1", 10, now=4)


def test_cancel_rest_restarts_grace():
    p = make()
    arrive(p)
    p.start_rest("u1", 120, now=3)
    assert p.end_rest("u1", now=50)["reason"] == "cancelled"
    assert p.observe(79, {}) == []
    assert types(p.observe(80, {})) == ["user_left"]


def test_rest_counter_resets_after_session_ends():
    p = make(max_rests=1)
    arrive(p)
    p.start_rest("u1", 1, now=3)
    p.observe(40, {})  # rest expired + grace passed -> left
    assert "u1" not in p.users
    arrive(p, t0=100)
    p.start_rest("u1", 1, now=103)  # allowed again


def test_unknown_face_with_cooldown():
    p = make()
    assert p.observe(0, {}, unknown_faces=1) == []
    assert p.observe(1, {}, unknown_faces=1) == []
    assert types(p.observe(2, {}, unknown_faces=1)) == ["unknown_face"]
    assert p.observe(3, {}, unknown_faces=1) == []
    assert p.observe(30, {}, unknown_faces=1) == []
    assert p.observe(31, {}, unknown_faces=1) == []
    assert types(p.observe(32, {}, unknown_faces=1)) == ["unknown_face"]


def test_two_users_independent():
    p = make()
    for i in range(3):
        p.observe(i, {"u1": 0.7, "u2": 0.6})
    p.observe(20, {"u2": 0.6})
    evs = p.observe(32, {"u2": 0.6})
    assert types(evs) == ["user_left"] and evs[0]["user_id"] == "u1"
    assert "u2" in p.users


def test_camera_offline_time_not_counted():
    p = make()
    arrive(p)
    p.shift_time(60)  # camera was down for a minute
    assert p.observe(61, {}) == []


# ------------------------------------------------------------------ face tracker
_rng = np.random.default_rng(1)
FACE_A = _rng.normal(size=512); FACE_A /= np.linalg.norm(FACE_A)
FACE_B = _rng.normal(size=512); FACE_B /= np.linalg.norm(FACE_B)


class F:
    def __init__(self, x, emb=FACE_A, width=100):
        self.bbox = np.array([x, 100, x + width, 100 + width], float)
        self.width, self.det_score = float(width), 0.9
        noisy = emb + _rng.normal(scale=0.03, size=512)
        self.embedding = noisy / np.linalg.norm(noisy)


def matcher(results):
    """Fake gallery: returns the queued Match results in order."""
    it = iter(results)
    return lambda emb: next(it)


def test_tracker_keeps_identity_through_bad_frames():
    tr = FaceTracker()
    for t in range(5):
        tr.update([F(100 + t)], t * 0.2, lambda e: Match("u1", 0.7))
    # face turned away: still detected, but recognition fails for a few frames
    for t in range(5, 8):
        seen = tr.update([F(100 + t)], t * 0.2, lambda e: Match(None, 0.2))
        assert seen[0].identity == "u1"


def test_tracker_new_person_new_track():
    tr = FaceTracker()
    tr.update([F(100)], 0, lambda e: Match("u1", 0.7))
    seen = tr.update([F(100), F(500, FACE_B)], 0.2, matcher([Match("u1", 0.7), Match(None, 0.1)]))
    assert [s.identity for s in seen] == ["u1", UNKNOWN]
    assert seen[0].id != seen[1].id


def test_track_embedding_is_averaged():
    """A single noisy frame barely moves the track's embedding."""
    tr = FaceTracker()
    for t in range(5):
        tr.update([F(100)], t * 0.2, lambda e: Match(None, 0))
    tr.update([F(100, FACE_B, width=30)], 1.0, lambda e: Match(None, 0))  # small, junk frame
    assert float(tr.tracks[0].embedding @ FACE_A) > 0.9


def test_person_swap_resets_track():
    tr = FaceTracker()
    for t in range(5):
        tr.update([F(100)], t * 0.2, lambda e: Match("u1", 0.7))
    seen = tr.update([F(100, FACE_B)], 1.2, lambda e: Match("u2", 0.7))
    assert seen[0].identity == "u2"
    assert float(seen[0].embedding @ FACE_A) < 0.15   # nothing of the previous person left
