def _iso(dt) -> str | None:
    return dt.isoformat() if dt else None


def entry_to_public(doc: dict, users_by_id: dict[str, dict]) -> dict:
    return {
        "id": str(doc["_id"]),
        "machine_id": str(doc["machine_id"]),
        "state": doc["state"],
        "grace_reason": doc.get("grace_reason"),
        "joined_at": _iso(doc.get("joined_at")),
        "active_started_at": _iso(doc.get("active_started_at")),
        "grace_deadline": _iso(doc.get("grace_deadline")),
        "rest_started_at": _iso(doc.get("rest_started_at")),
        "rest_deadline": _iso(doc.get("rest_deadline")),
        "rest_count": doc.get("rest_count", 0),
        "users": [
            {
                "id": str(uid),
                "display_name": users_by_id.get(str(uid), {}).get("display_name") or "Unknown",
            }
            for uid in doc["user_ids"]
        ],
    }


async def resolve_users_by_id(db, user_ids: list) -> dict[str, dict]:
    if not user_ids:
        return {}
    cursor = db.users.find({"_id": {"$in": list(user_ids)}})
    docs = await cursor.to_list(length=None)
    return {str(d["_id"]): d for d in docs}
