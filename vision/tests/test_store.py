import json

import httpx
import numpy as np

from gymvision.store import SupabaseFaceStore


def test_supabase_store_roundtrip():
    rows: list[dict] = []
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append((req.method, req.url.path, dict(req.url.params), req.headers.get("authorization")))
        if req.method == "POST":
            rows.extend(json.loads(req.content))
            return httpx.Response(201)
        if req.method == "DELETE":
            uid = req.url.params["user_id"].removeprefix("eq.")
            rows[:] = [r for r in rows if r["user_id"] != uid]
            return httpx.Response(204)
        # pgvector columns come back as strings
        return httpx.Response(200, json=[{**r, "embedding": json.dumps(r["embedding"])} for r in rows])

    store = SupabaseFaceStore("https://x.supabase.co", "service-key")
    store.client = httpx.Client(transport=httpx.MockTransport(handler), headers=store.client.headers)

    e = np.ones(512, np.float32) / np.sqrt(512)
    store.save_user("u1", {"center": e, "left": e})
    store.save_user("u1", {"center": e})  # re-scan replaces old poses
    loaded = store.load_all()

    assert [(r.user_id, r.pose) for r in loaded] == [("u1", "center")]
    assert np.allclose(loaded[0].embedding, e, atol=1e-5)
    assert seen[0][:3] == ("DELETE", "/rest/v1/face_embeddings", {"user_id": "eq.u1"})
    assert all(s[3] == "Bearer service-key" for s in seen)
