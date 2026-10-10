"""Lookups against the GymQueue backend (needs BACKEND_URL + BACKEND_API_KEY)."""
from __future__ import annotations

import httpx

from .config import settings


def machines() -> list[dict]:
    """[{"id", "name", "campus"}] - ids to use as machine_id in cameras.json."""
    if not settings.backend_url:
        raise SystemExit("BACKEND_URL is not set (vision/.env), so GymQueue can't be reached")
    r = httpx.get(f"{settings.backend_url}/api/vision/machines", timeout=10,
                  headers={"Authorization": f"Bearer {settings.backend_api_key}"})
    if r.status_code == 401:
        raise SystemExit("backend refused the key: BACKEND_API_KEY here must equal VISION_EVENTS_API_KEY in backend/.env")
    r.raise_for_status()
    return r.json()
