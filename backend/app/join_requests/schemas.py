def request_to_public(doc: dict, users_by_id: dict[str, dict]) -> dict:
    requester = users_by_id.get(str(doc["requester_id"]), {})
    target = users_by_id.get(str(doc["target_id"]), {})
    return {
        "id": str(doc["_id"]),
        "machine_id": str(doc["machine_id"]),
        "queue_entry_id": str(doc["queue_entry_id"]),
        "requester_id": str(doc["requester_id"]),
        "requester_display_name": requester.get("display_name") or "Unknown",
        "target_id": str(doc["target_id"]),
        "target_display_name": target.get("display_name") or "Unknown",
        "status": doc["status"],
        "created_at": doc["created_at"].isoformat(),
        "resolved_at": doc["resolved_at"].isoformat() if doc.get("resolved_at") else None,
    }
