"""Spoken announcements via ElevenLabs TTS, for the events where missing a toast
actually costs you something: your turn starting, a rest period expiring, someone
asking to work in on your machine, and your end-of-use grace period timing out.
Every other notification stays toast-only - speaking those would just be noisy.

Synthesized audio is cached in memory keyed by the exact text, so a repeated phrase
(same machine, same wording) is billed once, not once per occurrence - ElevenLabs
bills by characters synthesized. Best-effort throughout: any failure here just means
no audio for that notification, never blocks the notification itself from being sent.
"""
from __future__ import annotations

import hashlib
import logging

import httpx

from app.config import settings
from app.models.common import EventType

log = logging.getLogger(__name__)

BASE_URL = "https://api.elevenlabs.io"
_TIMEOUT = 15.0

_cache: dict[str, bytes] = {}  # audio id -> mp3 bytes
_voice_id: str | None = None   # resolved once per process, unless ELEVENLABS_VOICE_ID is set


def enabled() -> bool:
    return bool(settings.elevenlabs_api_key)


def get_cached(audio_id: str) -> bytes | None:
    return _cache.get(audio_id)


def _headers() -> dict[str, str]:
    return {"xi-api-key": settings.elevenlabs_api_key}


def _speak_text(event_type: EventType, payload: dict) -> str | None:
    if event_type == EventType.YOUR_TURN:
        return f"It's your turn! {payload.get('machine_name') or 'Your machine'} is ready for you."
    if event_type == EventType.REST_EXPIRED:
        return "Your rest period expired. The machine is wrapping up your turn."
    if event_type == EventType.JOIN_REQUEST_RECEIVED:
        return f"{payload.get('requester_display_name') or 'Someone'} wants to work in on your machine."
    if event_type == EventType.SESSION_ENDED and payload.get("reason") == "grace_expired":
        # Only the timeout case - if you just clicked "leave" yourself, you're already
        # looking at the screen and don't need to be told what you just did.
        return "Your time has ended. The machine has been released."
    return None


async def _resolve_voice_id(client: httpx.AsyncClient) -> str | None:
    global _voice_id
    if settings.elevenlabs_voice_id:
        return settings.elevenlabs_voice_id
    if _voice_id is not None:
        return _voice_id
    r = await client.get(f"{BASE_URL}/v2/voices", headers=_headers())
    if r.status_code != 200:
        log.warning("ElevenLabs: could not list voices (%s): %s", r.status_code, r.text[:200])
        return None
    voices = r.json().get("voices", [])
    if not voices:
        log.warning("ElevenLabs: account has no voices available")
        return None
    _voice_id = voices[0]["voice_id"]
    return _voice_id


async def synthesize_for_event(event_type: EventType, payload: dict) -> str | None:
    """Audio id the frontend can fetch via GET /notifications/audio/{id}, or None if
    this event isn't spoken (or synthesis isn't configured/failed)."""
    if not enabled():
        return None
    text = _speak_text(event_type, payload)
    if text is None:
        return None
    audio_id = hashlib.sha256(text.encode()).hexdigest()[:16]
    if audio_id in _cache:
        return audio_id
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            voice_id = await _resolve_voice_id(client)
            if voice_id is None:
                return None
            r = await client.post(
                f"{BASE_URL}/v1/text-to-speech/{voice_id}",
                headers=_headers(),
                json={"text": text, "model_id": "eleven_turbo_v2_5"},
            )
            if r.status_code != 200:
                log.warning("ElevenLabs: synthesis failed (%s): %s", r.status_code, r.text[:200])
                return None
            _cache[audio_id] = r.content
            return audio_id
    except httpx.HTTPError as e:
        log.warning("ElevenLabs unreachable: %s", e)
        return None
