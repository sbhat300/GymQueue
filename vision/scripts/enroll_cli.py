"""Enroll a face from the laptop webcam (or any source) with an on-screen guide.

    python scripts/enroll_cli.py --user-id <supabase-user-uuid> --name "Nishant"
    python scripts/enroll_cli.py --user-id test1 --source esp32:http://192.168.43.50

Walks through center/left/right/up/down, then stores the embeddings in the configured
FACE_STORE (local JSON by default, Supabase if FACE_STORE=supabase). Press q to abort.
"""
import argparse
import sys
import time
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gymvision.camera import open_source  # noqa: E402
from gymvision.engine import FaceEngine  # noqa: E402
from gymvision.enrollment import EnrollmentSession  # noqa: E402
from gymvision.gallery import Gallery  # noqa: E402
from gymvision.store import make_store  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--user-id", required=True)
    ap.add_argument("--name", default="")
    ap.add_argument("--source", default="webcam:0")
    ap.add_argument("--no-mirror", action="store_true", help="don't flip the preview like a mirror")
    args = ap.parse_args()

    engine = FaceEngine.shared()
    store = make_store()
    gallery = Gallery(store)
    gallery.reload()
    sess = EnrollmentSession(args.user_id, args.name)
    src = open_source(args.source).start()

    seq = -1
    win = "Face scan - press q to quit"
    while True:
        seq_new, _, frame = src.latest(seq)
        if frame is None:
            if cv2.waitKey(10) & 0xFF == ord("q"):
                return 1
            continue
        seq = seq_new
        res = sess.add_frame(frame, engine)

        view = frame.copy()
        if res.face is not None:
            x1, y1, x2, y2 = res.face.bbox.astype(int)
            cv2.rectangle(view, (x1, y1), (x2, y2), (60, 200, 60) if res.accepted else (0, 200, 255), 2)
        if not args.no_mirror:
            view = cv2.flip(view, 1)
        h, w = view.shape[:2]
        cv2.rectangle(view, (0, 0), (w, 70), (0, 0, 0), -1)
        st = sess.status()
        cv2.putText(view, st["instruction"], (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
        cv2.putText(view, res.message, (12, 58), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (60, 220, 60) if res.accepted else (0, 200, 255), 2)
        cv2.rectangle(view, (0, h - 12), (int(w * sess.progress), h), (60, 200, 60), -1)
        steps = "  ".join(f"{p}:{n}/{st['samples_per_pose']}" for p, n in st["samples"].items())
        cv2.putText(view, steps, (12, h - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        cv2.imshow(win, view)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            print("aborted")
            return 1
        if sess.done:
            break

    src.stop()
    try:
        result = sess.finish(store, gallery)
    except PermissionError as e:
        print("REFUSED:", e)
        return 2
    print("enrolled:", result)
    time.sleep(0.5)
    cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    sys.exit(main())
