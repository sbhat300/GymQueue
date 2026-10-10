"""Quick local test: recognise + track presence on one camera, shown in a window.

    python scripts/live.py --source webcam:0
    python scripts/live.py --source esp32:http://192.168.43.50 --grace 10
    python scripts/live.py --roi 0.25,0.1,0.75,0.9    # only look at the middle of the frame

Events print to the terminal (nothing is sent to the backend unless BACKEND_URL is set).
Keys: r = start a 20s rest for the first present user, q = quit.
"""
import argparse
import logging
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gymvision.config import CameraConfig  # noqa: E402
from gymvision.engine import FaceEngine  # noqa: E402
from gymvision.events import EventSink  # noqa: E402
from gymvision.gallery import Gallery  # noqa: E402
from gymvision.store import make_store  # noqa: E402
from gymvision.worker import MachineWorker  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="webcam:0")
    ap.add_argument("--machine-id", default="test-machine")
    ap.add_argument("--grace", type=float, default=None, help="override AWAY_GRACE_S")
    ap.add_argument("--roi", default=None, help="machine area x1,y1,x2,y2 as fractions, e.g. 0.25,0.1,0.75,0.9")
    args = ap.parse_args()
    roi = [float(v) for v in args.roi.split(",")] if args.roi else None

    gallery = Gallery(make_store())
    gallery.reload()
    w = MachineWorker(CameraConfig(args.machine_id, args.source, "live test", roi),
                      FaceEngine.shared(), gallery, EventSink())
    if args.grace is not None:
        w.presence.away_grace_s = args.grace
    w.start()

    last = -1
    while True:
        seq, jpeg = w.latest_jpeg()
        if jpeg is not None and seq != last:
            last = seq
            cv2.imshow("gym vision - q to quit, r to rest", cv2.imdecode(np.frombuffer(jpeg, np.uint8), 1))
        k = cv2.waitKey(20) & 0xFF
        if k == ord("q"):
            break
        if k == ord("r"):
            with w.lock:
                users = list(w.presence.users)
                if users:
                    try:
                        w.sink.emit([w.presence.start_rest(users[0], 20, time.time())])
                    except Exception as e:
                        print("rest refused:", e)
    w.stop()


if __name__ == "__main__":
    main()
