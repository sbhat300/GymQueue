"""Best-effort commands to the vision service, so its presence tracker stays in sync
with rest/release actions that originate from the app (button taps, API calls).

The vision service is supplementary, not source of truth: if it's unreachable or
unconfigured, these calls are silently skipped and the queue state machine in
app/queue/service.py proceeds exactly as it does today.
"""
import logging

import httpx

from app.config import settings

log = logging.getLogger(__name__)

_TIMEOUT = 3.0


async def _post(path: str, json: dict) -> None:
    if not settings.vision_url:
        return
    headers = {"Authorization": f"Bearer {settings.vision_api_key}"} if settings.vision_api_key else {}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            await client.post(f"{settings.vision_url}{path}", json=json, headers=headers)
    except httpx.HTTPError as e:
        log.warning("vision service unreachable (%s %s): %s", path, json, e)


async def _delete(path: str, json: dict) -> None:
    if not settings.vision_url:
        return
    headers = {"Authorization": f"Bearer {settings.vision_api_key}"} if settings.vision_api_key else {}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            await client.request("DELETE", f"{settings.vision_url}{path}", json=json, headers=headers)
    except httpx.HTTPError as e:
        log.warning("vision service unreachable (%s %s): %s", path, json, e)


async def notify_rest_started(machine_id: str, user_id: str, seconds: float) -> None:
    await _post(f"/machines/{machine_id}/rest", {"user_id": user_id, "seconds": seconds})


async def notify_rest_ended(machine_id: str, user_id: str) -> None:
    await _delete(f"/machines/{machine_id}/rest", {"user_id": user_id})


async def notify_release(machine_id: str, user_id: str) -> None:
    await _post(f"/machines/{machine_id}/release", {"user_id": user_id})
