import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class WorkflowRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = None
    topology: dict = Field(default_factory=dict)


class WorkflowUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None
    topology: dict | None = None


class TriggerRequest(BaseModel):
    task_input: dict = Field(default_factory=dict)


class WorkflowListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None = None
    created_at: datetime


class WorkflowResponse(WorkflowListItem):
    topology: dict
