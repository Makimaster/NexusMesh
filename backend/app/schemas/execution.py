import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ExecutionListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workflow_id: uuid.UUID | None = None
    status: str
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class ExecutionResponse(ExecutionListItem):
    input: dict
    output: dict | None = None
    error: str | None = None


class ExecutionAcceptedResponse(BaseModel):
    execution_id: uuid.UUID


class TimelineEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    execution_id: uuid.UUID | None = None
    protocol_stage: str
    event_type: str
    payload: dict
    created_at: datetime
