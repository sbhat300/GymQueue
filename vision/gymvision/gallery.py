"""In-memory face gallery: cosine-similarity matching against every enrolled embedding."""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

import numpy as np

from .config import settings
from .store import FaceStore

log = logging.getLogger(__name__)


@dataclass
class Match:
    user_id: str | None   # None = unknown face
    score: float          # best cosine similarity
    label: str = ""


class Gallery:
    def __init__(self, store: FaceStore, threshold: float = settings.match_threshold,
                 margin: float = settings.match_margin):
        self.store = store
        self.threshold = threshold
        self.margin = margin
        self._lock = threading.Lock()
        self._matrix = np.zeros((0, 512), np.float32)
        self._owners: np.ndarray = np.array([], dtype=object)
        self._labels: dict[str, str] = {}
        self.loaded_at = 0.0

    def reload(self) -> None:
        rows = self.store.load_all()
        matrix = np.stack([r.embedding for r in rows]).astype(np.float32) if rows else np.zeros((0, 512), np.float32)
        if len(matrix):
            matrix /= np.linalg.norm(matrix, axis=1, keepdims=True)
        with self._lock:
            self._matrix = matrix
            self._owners = np.array([r.user_id for r in rows], dtype=object)
            self._labels = {r.user_id: r.label for r in rows if r.label}
            self.loaded_at = time.time()
        log.info("gallery loaded: %d embeddings, %d users", len(rows), len(set(self._owners)))

    def maybe_reload(self, every_s: float = settings.gallery_refresh_s) -> None:
        if time.time() - self.loaded_at >= every_s:
            try:
                self.reload()
            except Exception as e:
                log.warning("gallery reload failed, keeping old copy: %s", e)

    @property
    def user_count(self) -> int:
        with self._lock:
            return len(set(self._owners))

    def label(self, user_id: str) -> str:
        return self._labels.get(user_id, "")

    def scores(self, embedding: np.ndarray) -> dict[str, float]:
        """Best similarity per user (max over that user's poses)."""
        with self._lock:
            if not len(self._matrix):
                return {}
            sims = self._matrix @ embedding.astype(np.float32)
            owners = self._owners
        best: dict[str, float] = {}
        for uid, s in zip(owners, sims):
            if s > best.get(uid, -1.0):
                best[uid] = float(s)
        return best

    def match(self, embedding: np.ndarray, exclude: str | None = None) -> Match:
        per_user = self.scores(embedding)
        if exclude:
            per_user.pop(exclude, None)
        if not per_user:
            return Match(None, 0.0)
        ranked = sorted(per_user.items(), key=lambda kv: kv[1], reverse=True)
        uid, top = ranked[0]
        runner_up = ranked[1][1] if len(ranked) > 1 else -1.0
        if top >= self.threshold and top - runner_up >= self.margin:
            return Match(uid, top, self.label(uid))
        return Match(None, top)
