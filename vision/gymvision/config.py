"""Runtime settings, read from environment variables (and an optional .env file)."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _f(name: str, default: float) -> float:
    return float(os.getenv(name, default))


def _i(name: str, default: int) -> int:
    return int(os.getenv(name, default))


@dataclass
class CameraConfig:
    machine_id: str
    source: str | list[str]   # one source, or several to fall back between (camera.py)
    name: str = ""
    # Optional machine area [x1, y1, x2, y2] as fractions of the frame, e.g. [0.25, 0.1, 0.75, 0.8].
    # Only this region is searched: faces there are effectively zoomed in (recognised from further
    # away) and people walking past in the background are ignored.
    roi: list[float] | None = None
    # Optional exercise to count reps for on this machine (currently "shoulder_press").
    exercise: str | None = None


@dataclass
class Settings:
    # --- model ---
    model_name: str = field(default_factory=lambda: os.getenv("INSIGHTFACE_MODEL", "buffalo_l"))
    det_size: int = field(default_factory=lambda: _i("DET_SIZE", 640))

    # --- matching ---
    match_threshold: float = field(default_factory=lambda: _f("MATCH_THRESHOLD", 0.45))
    match_margin: float = field(default_factory=lambda: _f("MATCH_MARGIN", 0.05))
    min_face_px: int = field(default_factory=lambda: _i("MIN_FACE_PX", 20))

    # --- presence (part 7) ---
    arrive_hits: int = field(default_factory=lambda: _i("ARRIVE_HITS", 3))
    arrive_window_s: float = field(default_factory=lambda: _f("ARRIVE_WINDOW_S", 4.0))
    away_grace_s: float = field(default_factory=lambda: _f("AWAY_GRACE_S", 15.0))
    rest_default_s: float = field(default_factory=lambda: _f("REST_DEFAULT_S", 120.0))
    max_rests: int = field(default_factory=lambda: _i("MAX_RESTS", 6))
    unknown_cooldown_s: float = field(default_factory=lambda: _f("UNKNOWN_COOLDOWN_S", 30.0))
    heartbeat_s: float = field(default_factory=lambda: _f("HEARTBEAT_S", 3.0))
    max_fps: float = field(default_factory=lambda: _f("MAX_FPS", 5.0))         # face recognition, per camera
    pose_fps: float = field(default_factory=lambda: _f("POSE_FPS", 15.0))      # rep counting, per camera
    # CPU threads for the face model. Using every core makes the models fight each other;
    # 4 measured ~3x faster than the default on a 16-core laptop.
    ort_threads: int = field(default_factory=lambda: _i("ORT_THREADS", 4))


    # --- storage ---
    face_store: str = field(default_factory=lambda: os.getenv("FACE_STORE", "local"))  # local | supabase
    local_store_path: str = field(default_factory=lambda: os.getenv("LOCAL_STORE_PATH", str(ROOT / "data" / "faces.json")))
    supabase_url: str = field(default_factory=lambda: os.getenv("SUPABASE_URL", ""))
    supabase_service_key: str = field(default_factory=lambda: os.getenv("SUPABASE_SERVICE_ROLE_KEY", ""))
    supabase_table: str = field(default_factory=lambda: os.getenv("SUPABASE_FACE_TABLE", "face_embeddings"))
    gallery_refresh_s: float = field(default_factory=lambda: _f("GALLERY_REFRESH_S", 30.0))

    # --- backend communication ---
    backend_url: str = field(default_factory=lambda: os.getenv("BACKEND_URL", "").rstrip("/"))
    backend_events_path: str = field(default_factory=lambda: os.getenv("BACKEND_EVENTS_PATH", "/api/vision/events"))
    backend_api_key: str = field(default_factory=lambda: os.getenv("BACKEND_API_KEY", ""))

    # --- this service's own API ---
    api_key: str = field(default_factory=lambda: os.getenv("VISION_API_KEY", ""))
    # Requests from this laptop itself (localhost) don't need the key, so the live view opens
    # without ?key=. Turn OFF if you put the service behind a tunnel (ngrok, cloudflared, ...):
    # tunnelled internet traffic also arrives from localhost.
    localhost_skips_key: bool = field(
        default_factory=lambda: os.getenv("LOCALHOST_SKIPS_KEY", "true").lower() not in ("0", "false", "no", "off"))
    cameras_file: str = field(default_factory=lambda: os.getenv("CAMERAS_FILE", str(ROOT / "cameras.json")))

    def cameras(self) -> list[CameraConfig]:
        path = Path(self.cameras_file)
        if not path.exists():
            return []
        return [CameraConfig(**c) for c in json.loads(path.read_text())]


settings = Settings()
