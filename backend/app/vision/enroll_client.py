"""Proxy to the vision service's face-scan API (vision/README.md, "Face registration").

Unlike app/vision/client.py (best-effort presence commands), enrollment has no
fallback: if the vision service is down, enrollment simply cannot happen, so these
calls raise and let the caller show the user a real error instead of pretending to
succeed.
"""
import httpx
from fastapi import HTTPException, status

from app.config import settings

_TIMEOUT = 10.0  # a frame goes through face detection + embedding, budget generously


def _headers() -> dict:
    return {"Authorization": f"Bearer {settings.vision_api_key}"} if settings.vision_api_key else {}


async def _request(method: str, path: str, **kwargs) -> dict:
    if not settings.vision_url:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Face enrollment isn't set up for this gym yet")
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as http_client:
            r = await http_client.request(method, f"{settings.vision_url}{path}", headers=_headers(), **kwargs)
    except httpx.HTTPError:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Face enrollment service is unreachable")

    if r.status_code >= 400:
        detail = r.text
        if r.headers.get("content-type", "").startswith("application/json"):
            detail = r.json().get("detail", detail)
        raise HTTPException(r.status_code, detail)
    return r.json()


async def start(user_id: str, label: str) -> dict:
    return await _request("POST", "/enroll/start", json={"user_id": user_id, "label": label})


async def send_frame(session_id: str, image_data_url: str) -> dict:
    return await _request("POST", f"/enroll/{session_id}/frame", json={"image": image_data_url})


async def finish(session_id: str) -> dict:
    return await _request("POST", f"/enroll/{session_id}/finish")


async def cancel(session_id: str) -> dict:
    return await _request("DELETE", f"/enroll/{session_id}")
