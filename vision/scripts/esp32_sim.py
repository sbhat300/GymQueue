"""Pretend to be an ESP32-CAM until the real one arrives.

Serves the same endpoints as firmware/esp32cam (/capture, /stream, /status) using the
laptop webcam or a video file, so the full ESP32 -> HTTP -> Python path can be tested:

    python scripts/esp32_sim.py --source webcam:0 --port 8081
    # then in cameras.json use  "source": "esp32:http://127.0.0.1:8081"

You can also run it on a second laptop on the hotspot to test over real Wi-Fi.
"""
import argparse
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gymvision.camera import open_source  # noqa: E402

SRC = None
QUALITY = 80
WIDTH = 1280  # matches the firmware's default FRAMESIZE_HD


def jpeg():
    _, _, frame = SRC.latest()
    if frame is None:
        return None
    h, w = frame.shape[:2]
    if w > WIDTH:
        frame = cv2.resize(frame, (WIDTH, int(h * WIDTH / w)))
    return cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, QUALITY])[1].tobytes()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/capture":
            data = jpeg()
            if data is None:
                self.send_error(503, "camera not ready")
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif path == "/stream":
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.end_headers()
            try:
                while True:
                    data = jpeg()
                    if data:
                        self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + data + b"\r\n")
                    time.sleep(0.08)
            except (BrokenPipeError, ConnectionResetError):
                pass
        elif path == "/status":
            body = b'{"device":"esp32-sim","ok":true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404)


def main():
    global SRC, WIDTH
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="webcam:0")
    ap.add_argument("--port", type=int, default=8081)
    ap.add_argument("--width", type=int, default=WIDTH, help="downscale frames to this width")
    args = ap.parse_args()
    WIDTH = args.width
    SRC = open_source(args.source).start()
    print(f"fake ESP32-CAM on http://0.0.0.0:{args.port}  (/capture /stream /status)", flush=True)
    ThreadingHTTPServer(("0.0.0.0", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
