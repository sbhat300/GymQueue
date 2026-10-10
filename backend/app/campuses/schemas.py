def campus_to_public(doc: dict) -> dict:
    return {"id": str(doc["_id"]), "name": doc["name"], "slug": doc["slug"]}
