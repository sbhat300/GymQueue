from pydantic import BaseModel, Field


class SetProfileRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=80)


def user_to_public(doc: dict) -> dict:
    return {
        "id": str(doc["_id"]),
        "netid": doc["netid"],
        "display_name": doc.get("display_name"),
        "onboarding_complete": doc.get("onboarding_complete", False),
    }
