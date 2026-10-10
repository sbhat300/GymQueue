"""Where face embeddings live.

LocalFaceStore    JSON file on the laptop (default; works with no internet / no DB yet)
SupabaseFaceStore a Supabase table, via the PostgREST API with the service-role key.
                  The table is owned by the DB/backend side; this code only expects:
                      user_id   uuid / text
                      pose      text          ("center", "left", "right", "up", "down")
                      embedding vector(512) or float8[]
                      unique (user_id, pose)
                  RLS should allow NO client access: only the service role reads biometrics.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
import numpy as np

from .config import settings

log = logging.getLogger(__name__)


@dataclass
class StoredEmbedding:
    user_id: str
    pose: str
    embedding: np.ndarray
    label: str = ""   # optional display name (local store only; handy for the debug view)


class FaceStore:
    def load_all(self) -> list[StoredEmbedding]: ...
    def save_user(self, user_id: str, embeddings: dict[str, np.ndarray], label: str = "") -> None: ...
    def delete_user(self, user_id: str) -> None: ...


class LocalFaceStore(FaceStore):
    def __init__(self, path: str = settings.local_store_path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def _read(self) -> dict:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text())

    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data))
        tmp.replace(self.path)

    def load_all(self) -> list[StoredEmbedding]:
        with self._lock:
            data = self._read()
        return [
            StoredEmbedding(uid, pose, np.asarray(vec, dtype=np.float32), u.get("label", ""))
            for uid, u in data.items()
            for pose, vec in u["poses"].items()
        ]

    def save_user(self, user_id, embeddings, label=""):
        with self._lock:
            data = self._read()
            data[user_id] = {
                "label": label,
                "updated_at": time.time(),
                "poses": {p: e.astype(float).round(6).tolist() for p, e in embeddings.items()},
            }
            self._write(data)

    def delete_user(self, user_id):
        with self._lock:
            data = self._read()
            data.pop(user_id, None)
            self._write(data)


class SupabaseFaceStore(FaceStore):
    def __init__(self, url: str = settings.supabase_url, key: str = settings.supabase_service_key,
                 table: str = settings.supabase_table):
        if not url or not key:
            raise RuntimeError("FACE_STORE=supabase needs SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY")
        self.endpoint = f"{url.rstrip('/')}/rest/v1/{table}"
        self.client = httpx.Client(timeout=10.0, headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        })

    @staticmethod
    def _parse(vec) -> np.ndarray:
        # pgvector comes back as the string "[0.1,0.2,...]"; float8[] comes back as a JSON list
        if isinstance(vec, str):
            vec = json.loads(vec)
        return np.asarray(vec, dtype=np.float32)

    def load_all(self):
        rows, start, page = [], 0, 1000
        while True:
            r = self.client.get(self.endpoint, params={"select": "user_id,pose,embedding"},
                                headers={"Range": f"{start}-{start + page - 1}"})
            r.raise_for_status()
            batch = r.json()
            rows += batch
            if len(batch) < page:
                break
            start += page
        return [StoredEmbedding(str(r["user_id"]), r["pose"], self._parse(r["embedding"])) for r in rows]

    def save_user(self, user_id, embeddings, label=""):
        # replace the user's whole set so a re-scan never leaves stale poses behind
        self.delete_user(user_id)
        body = [{"user_id": user_id, "pose": p, "embedding": e.astype(float).round(6).tolist()}
                for p, e in embeddings.items()]
        r = self.client.post(self.endpoint, json=body, headers={"Prefer": "return=minimal"})
        r.raise_for_status()

    def delete_user(self, user_id):
        r = self.client.delete(self.endpoint, params={"user_id": f"eq.{user_id}"})
        r.raise_for_status()


def make_store() -> FaceStore:
    if settings.face_store == "supabase":
        return SupabaseFaceStore()
    return LocalFaceStore()
