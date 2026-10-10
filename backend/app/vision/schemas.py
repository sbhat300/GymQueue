from pydantic import BaseModel, ConfigDict


class VisionEvent(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    type: str
    machine_id: str
    ts: float
    at: str


class VisionEventBatch(BaseModel):
    events: list[VisionEvent]
