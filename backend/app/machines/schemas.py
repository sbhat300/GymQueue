from app.config import settings


def machine_to_public(doc: dict) -> dict:
    return {
        "id": str(doc["_id"]),
        "campus_id": str(doc["campus_id"]),
        "name": doc["name"],
        "category": doc["category"],
        "is_active": doc.get("is_active", True),
        "grace_period_seconds": doc.get("grace_period_seconds") or settings.default_grace_period_seconds,
        "rest_period_seconds": doc.get("rest_period_seconds") or settings.default_rest_period_seconds,
        "max_rests": doc.get("max_rests") or settings.default_max_rests,
    }
