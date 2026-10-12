from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Category = Literal["校园网络", "账号登录", "软件服务", "设备故障", "其他"]
Status = Literal["open", "in_progress", "awaiting_student", "resolved", "closed"]


class LoginInput(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=256)
    entry_role: Literal["student", "admin"] | None = None


class TextInput(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


class RetrievalCompareInput(TextInput):
    first_mode: Literal["vector", "hybrid"] = "vector"


class TicketInput(BaseModel):
    draft_id: UUID
    title: str = Field(min_length=1, max_length=120)
    category: Category
    description: str = Field(min_length=1, max_length=8000)
    location: str = Field(default="", max_length=120)


class StatusInput(BaseModel):
    status: Status


class VisibilityInput(BaseModel):
    visibility: Literal["public", "admin"]


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer: str = Field(max_length=12000)
    answerable: bool
    sources: list[int] = Field(default_factory=list, max_length=5)


class ConversationRoute(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["general", "knowledge"]


class DraftOutput(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    category: Category
    description: str = Field(min_length=1, max_length=8000)
