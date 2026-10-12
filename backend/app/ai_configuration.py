from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.config import settings
from app.db import get_db
from app.errors import AppError
from app.models import AIConfiguration
from app.providers import CompatibleProvider, provider
from app.security import current_user

router = APIRouter(prefix="/api/v1/ai-config", tags=["AI configuration"])


class AIConfigurationInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, hide_input_in_errors=True)
    mode: Literal["cloud"] = "cloud"
    api_base: str = Field(default="", max_length=2048)
    model: str = Field(default="", max_length=200)
    api_key: str | None = Field(default=None, max_length=4096, repr=False)
    api_style: Literal["openai", "anthropic"] = "openai"

    @model_validator(mode="after")
    def validate_endpoint(self):
        url = urlsplit(self.api_base)
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
            or (url.port is not None and not 1 <= url.port <= 65535)
            or any(char.isspace() for char in self.api_base)
            or not self.model
        ):
            raise ValueError("Provide an HTTP(S) base URL without credentials and a model name")
        return self


def public_configuration(row):
    return {
        "mode": "cloud" if row else "default",
        "api_base": row.api_base if row else "",
        "model": row.model if row else "",
        "api_style": "anthropic" if row and row.api_style == "anthropic" else "openai",
        "has_api_key": bool(row and row.api_key),
    }


def resolve_configuration(body, row):
    key = body.api_key
    if key is None:
        # Never forward a stored credential to a newly selected endpoint.
        key = row.api_key if row and row.api_base.rstrip("/") == body.api_base.rstrip("/") else ""
    if body.mode == "cloud" and not key:
        raise AppError("AI_KEY_REQUIRED", "自定义模型需要填写 API Key；修改接口地址后请重新填写")
    return key


def configured_provider(row):
    cfg = settings().model_copy(
        update={
            "model_mode": "real",
            "llm_api_base": row.api_base,
            "llm_api_key": row.api_key,
            "llm_model": row.model,
            "llm_api_style": row.api_style,
            "llm_thinking_enabled": False,
            "llm_reasoning_effort": "",
            "llm_max_completion_tokens": None,
        }
    )
    return CompatibleProvider(chat_config=cfg)


def user_chat_provider(db, user_id, fallback=provider):
    row = db.get(AIConfiguration, user_id)
    return configured_provider(row) if row else fallback()


@router.get("")
def read_configuration(user=Depends(current_user), db=Depends(get_db)):
    return public_configuration(db.get(AIConfiguration, user.id))


@router.put("")
def save_configuration(body: AIConfigurationInput, user=Depends(current_user), db=Depends(get_db)):
    row = db.get(AIConfiguration, user.id)
    key = resolve_configuration(body, row)
    if row is None:
        row = AIConfiguration(user_id=user.id)
        db.add(row)
    for name in ("mode", "api_base", "model", "api_style"):
        setattr(row, name, getattr(body, name))
    row.api_key = key
    db.commit()
    return public_configuration(row)


@router.post("/test")
async def test_configuration(body: AIConfigurationInput, user=Depends(current_user), db=Depends(get_db)):
    key = resolve_configuration(body, db.get(AIConfiguration, user.id))
    row = AIConfiguration(**body.model_dump(exclude={"api_key"}), api_key=key)
    model = configured_provider(row)
    db.commit()
    await model.general_answer("你好，请简短回应。", [])
    return {"message": "连接成功，模型可正常回复"}
