import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AgentRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = None
    agent_type: str = Field(min_length=1, max_length=50)
    llm_provider: str = Field(min_length=1, max_length=50)
    llm_model: str = Field(min_length=1, max_length=100)
    system_prompt: str | None = None
    config: dict = Field(default_factory=dict)


class AgentUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None
    agent_type: str | None = Field(default=None, min_length=1, max_length=50)
    llm_provider: str | None = Field(default=None, min_length=1, max_length=50)
    llm_model: str | None = Field(default=None, min_length=1, max_length=100)
    system_prompt: str | None = None
    config: dict | None = None


class AgentListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    agent_type: str
    llm_provider: str
    llm_model: str
    created_at: datetime


class AgentResponse(AgentListItem):
    system_prompt: str | None = None
    config: dict
