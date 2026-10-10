import numpy as np
import pytest

import gymvision.enrollment as enr
from gymvision.engine import Face
from gymvision.enrollment import POSES, SAMPLES_PER_POSE, EnrollmentSession
from gymvision.gallery import Gallery
from gymvision.store import LocalFaceStore

rng = np.random.default_rng(0)
IMG = rng.integers(0, 255, (300, 300, 3), dtype=np.uint8)  # noisy = "sharp"


def unit(v):
    return (v / np.linalg.norm(v)).astype(np.float32)


PERSON_A = unit(rng.normal(size=512))
PERSON_B = unit(rng.normal(size=512))


def face(yaw=0.0, pitch=0.6, who=PERSON_A, size=200):
    # eyes 20px apart at y=50, mouth at y=75 -> yaw = dx/20, pitch = (nose_y-50)/25
    kps = np.array([[40, 50], [60, 50], [50 + yaw * 20, 50 + pitch * 25], [42, 75], [58, 75]], float)
    emb = unit(who + rng.normal(scale=0.02, size=512))
    return Face(np.array([0, 0, size, size], float), kps, 0.9, emb)


class FakeEngine:
    def __init__(self):
        self.next = []

    def detect(self, img, min_face_px=0):
        return self.next

    def embed_lowres(self, img, face, face_px):
        return unit(face.embedding + rng.normal(scale=0.05, size=512))


POSE_FACES = {
    "center": dict(yaw=0.0, pitch=0.6),
    "left": dict(yaw=0.35, pitch=0.6),
    "right": dict(yaw=-0.35, pitch=0.6),
    "up": dict(yaw=0.0, pitch=0.4),
    "down": dict(yaw=0.0, pitch=0.8),
}


@pytest.fixture(autouse=True)
def no_sample_gap(monkeypatch):
    monkeypatch.setattr(enr, "MIN_SAMPLE_GAP_S", 0.0)


def run_full_scan(sess, eng, who=PERSON_A):
    for pose in POSES:
        for _ in range(SAMPLES_PER_POSE):
            eng.next = [face(who=who, **POSE_FACES[pose])]
            assert sess.add_frame(IMG, eng).accepted, pose


def test_full_scan_and_store(tmp_path):
    store = LocalFaceStore(str(tmp_path / "f.json"))
    gallery = Gallery(store)
    sess, eng = EnrollmentSession("user-a", "A"), FakeEngine()
    run_full_scan(sess, eng)
    assert sess.done and sess.progress == 1.0
    out = sess.finish(store, gallery)
    assert set(out["poses"]) == set(POSES) | {"center_far", "left_far", "right_far"}
    assert gallery.match(face().embedding).user_id == "user-a"
    assert gallery.match(face(who=PERSON_B).embedding).user_id is None


def test_wrong_direction_rejected():
    sess, eng = EnrollmentSession("u"), FakeEngine()
    for _ in range(SAMPLES_PER_POSE):
        eng.next = [face()]
        sess.add_frame(IMG, eng)
    assert sess.step == "left"
    eng.next = [face(yaw=-0.35)]  # turned right instead
    r = sess.add_frame(IMG, eng)
    assert not r.accepted and "LEFT" in r.message
    eng.next = [face(yaw=0.05)]   # barely turned
    assert not sess.add_frame(IMG, eng).accepted


def test_baseline_is_personal():
    """Someone whose neutral pose already reads slightly turned still has to turn further."""
    sess, eng = EnrollmentSession("u"), FakeEngine()
    for _ in range(SAMPLES_PER_POSE):
        eng.next = [face(yaw=0.15)]
        sess.add_frame(IMG, eng)
    eng.next = [face(yaw=0.30)]   # only 0.15 more than their neutral
    assert not sess.add_frame(IMG, eng).accepted
    eng.next = [face(yaw=0.40)]
    assert sess.add_frame(IMG, eng).accepted


def test_center_requires_facing_camera():
    sess, eng = EnrollmentSession("u"), FakeEngine()
    eng.next = [face(yaw=0.5)]
    assert not sess.add_frame(IMG, eng).accepted


def test_person_swap_mid_scan_rejected():
    sess, eng = EnrollmentSession("u"), FakeEngine()
    for _ in range(SAMPLES_PER_POSE):
        eng.next = [face()]
        sess.add_frame(IMG, eng)
    eng.next = [face(who=PERSON_B, yaw=0.35)]
    r = sess.add_frame(IMG, eng)
    assert not r.accepted and "same person" in r.message


def test_two_people_rejected():
    sess, eng = EnrollmentSession("u"), FakeEngine()
    eng.next = [face(), face(who=PERSON_B, size=180)]
    assert "one person" in sess.add_frame(IMG, eng).message


def test_same_face_on_second_account_refused(tmp_path):
    store = LocalFaceStore(str(tmp_path / "f.json"))
    gallery = Gallery(store)
    eng = FakeEngine()
    s1 = EnrollmentSession("account-1")
    run_full_scan(s1, eng)
    s1.finish(store, gallery)
    s2 = EnrollmentSession("account-2")
    run_full_scan(s2, eng)
    with pytest.raises(PermissionError):
        s2.finish(store, gallery)
    # re-scanning your own account is fine
    s3 = EnrollmentSession("account-1")
    run_full_scan(s3, eng)
    s3.finish(store, gallery)


def test_finish_incomplete_raises(tmp_path):
    store = LocalFaceStore(str(tmp_path / "f.json"))
    with pytest.raises(ValueError):
        EnrollmentSession("u").finish(store, Gallery(store))
