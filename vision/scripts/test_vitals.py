"""Quick check that heart rate works end to end: records a clip from a webcam (or uses a video
file) and runs it through presage_vitals exactly the way the vision service does.

    python scripts/test_vitals.py                  # 20s from webcam 0 - sit still, face the camera, good light
    python scripts/test_vitals.py --camera 2 --seconds 25
    python scripts/test_vitals.py --video clip.mp4

Needs PRESAGE_API_KEY in .env and presage/build/presage_vitals (presage/setup.sh). Stop the
vision service first if it's using the same camera.
"""
import argparse
import json
import logging
import sys
import time
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gymvision.vitals import VitalsTracker  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")


def capture(cap: cv2.VideoCapture, seconds: float, live: bool) -> list:
    frames, t0 = [], time.time()
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        now = time.time() if live else t0 + cap.get(cv2.CAP_PROP_POS_MSEC) / 1000
        if now - t0 > seconds:
            break
        frames.append((now, frame))
        if live and len(frames) % 30 == 0:
            print(f"  {now - t0:4.1f}s / {seconds:.0f}s", end="\r", flush=True)
    return frames


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--video", help="use a video file instead of the webcam")
    ap.add_argument("--seconds", type=float, default=20.0)
    args = ap.parse_args()

    tracker = VitalsTracker("test", "shoulder_press", sink=None)
    if not tracker.enabled:
        sys.exit(f"vitals disabled: {tracker.disabled_reason}")

    cap = cv2.VideoCapture(args.video if args.video else args.camera)
    if not cap.isOpened():
        sys.exit(f"couldn't open {args.video or f'camera {args.camera}'} (in use by the vision service?)")
    if not args.video:
        # MJPG + 30fps: raw YUYV at 720p usually drops to ~10fps, and the SDK needs >=25
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FPS, 30)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        print(f"recording {args.seconds:.0f}s - sit still and face the camera")
    frames = capture(cap, args.seconds, live=not args.video)
    cap.release()
    if len(frames) < 2:
        sys.exit("no frames captured")

    fps = len(frames) / (frames[-1][0] - frames[0][0])
    print(f"\ncaptured {len(frames)} frames at {fps:.1f} fps - running SDK...")
    clip, stamps = tracker._write_clip(frames, fps)
    try:
        t0 = time.time()
        result = tracker._run_sdk(clip, stamps)
    finally:
        clip.unlink(missing_ok=True)
        stamps.unlink(missing_ok=True)
    if result is None:
        sys.exit("SDK run failed (see log above)")
    summary = {k: v for k, v in result.items() if not k.endswith("_samples")}
    print(f"done in {time.time() - t0:.1f}s:", json.dumps(summary))
    print(f"{len(result['hr_samples'])} heart rate / {len(result['rr_samples'])} breathing samples")


if __name__ == "__main__":
    main()
