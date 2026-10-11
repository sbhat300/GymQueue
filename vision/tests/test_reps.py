import math

from gymvision.pose import Pose
from gymvision.reps import SetTracker, ShoulderPressCounter, _angle

import numpy as np

SHOULDER_W = 100.0


def press_pose(t: float, visible: bool = True, wobble: float = 0.0, hands_visible: bool = True) -> Pose:
    """Synthetic person pressing: t=0 bottom (elbows ~90 deg, hands at ear height), t=1 locked out."""
    ls, rs = np.array([250.0, 300.0]), np.array([350.0, 300.0])
    pts = {"nose": (300, 240, 1), "l_hip": (260, 500, 1), "r_hip": (340, 500, 1)}
    for side, sh, out in (("l", ls, -1), ("r", rs, 1)):
        # elbow swings from out-and-level (bent) to above the shoulder (straight)
        elbow = sh + np.array([out * (70 - 40 * t), -10 - 80 * t])
        wrist = elbow + np.array([out * (-10 + 30 * t) * (1 - t), -70 - 10 * t]) + wobble
        if t > 0.9:  # locked out: wrist straight above elbow above shoulder
            elbow = sh + np.array([out * 15, -85])
            wrist = sh + np.array([out * 20, -170])
        pts[f"{side}_shoulder"] = (*sh, 1.0)
        pts[f"{side}_elbow"] = (*elbow, 1.0 if visible else 0.1)
        pts[f"{side}_wrist"] = (*wrist, 1.0 if visible and hands_visible else 0.1)
    return Pose(pts)


def run(counter, ts):
    return sum(counter.update(press_pose(t)) for t in ts)


def reps_motion(n: int, frames_per_rep: int = 12):
    out = []
    for _ in range(n):
        out += [0.5 - 0.5 * math.cos(2 * math.pi * i / frames_per_rep) for i in range(frames_per_rep)]
    return out + [0.0, 0.0, 0.0]


def test_pose_geometry_classifies_bottom_and_top():
    c = ShoulderPressCounter()
    assert c.classify(c.metrics(press_pose(0.0))) == "down"
    assert c.classify(c.metrics(press_pose(1.0))) == "up"


def test_counts_each_full_rep():
    c = ShoulderPressCounter()
    assert run(c, reps_motion(5)) == 5
    assert c.reps == 5


def test_half_reps_do_not_count():
    c = ShoulderPressCounter()
    half = [0.0, 0.0, 0.2, 0.4, 0.5, 0.4, 0.2, 0.0, 0.0] * 4  # never locks out
    assert run(c, half) == 0


def test_starting_with_arms_up_waits_for_a_full_rep():
    c = ShoulderPressCounter()
    assert run(c, [1.0, 1.0, 1.0]) == 0
    assert run(c, [0.0, 0.0, 0.0, 1.0, 1.0]) == 1


def test_counts_reps_with_hands_out_of_frame():
    """Close to a webcam the hands leave the top of the picture at lockout - go by the elbows."""
    c = ShoulderPressCounter()
    reps = sum(c.update(press_pose(t, hands_visible=t < 0.6)) for t in reps_motion(4))
    assert reps == 4


def test_single_bad_frame_is_ignored():
    c = ShoulderPressCounter()
    assert run(c, [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0]) == 0  # one-frame "lockout" glitch


def test_arms_not_visible_counts_nothing():
    c = ShoulderPressCounter()
    assert sum(c.update(press_pose(t, visible=False)) for t in reps_motion(3)) == 0
    assert c.update(None) is False


def test_angle_helper():
    assert round(_angle(np.array([1.0, 0]), np.array([0.0, 0]), np.array([0.0, 1]))) == 90


# ------------------------------------------------------------------ sets
def test_set_ends_after_idle_time():
    s = SetTracker("shoulder_press", idle_s=15)
    for t in range(5):
        assert s.add_rep("u1", t * 3.0) is None
    assert s.expire(20.0) is None
    done = s.expire(12.0 + 15.0)
    assert done == {"user_id": "u1", "exercise": "shoulder_press", "reps": 5, "started_at": 0.0, "ended_at": 12.0}
    assert s.reps == 0


def test_new_person_starts_a_new_set():
    s = SetTracker("shoulder_press")
    s.add_rep("u1", 0)
    s.add_rep("u1", 3)
    done = s.add_rep("u2", 6)
    assert done["user_id"] == "u1" and done["reps"] == 2
    assert (s.user_id, s.reps) == ("u2", 1)


def test_face_hidden_mid_set_keeps_the_set():
    s = SetTracker("shoulder_press")
    s.add_rep("u1", 0)
    assert s.add_rep(None, 3) is None  # face behind arms at lockout
    assert (s.user_id, s.reps) == ("u1", 2)
