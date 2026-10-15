import uuid
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.ai_configuration import AIConfigurationInput, configured_provider, router, user_chat_provider
from app.config import Settings
from app.db import get_db
from app.models import AIConfiguration, User
from app.providers import CompatibleProvider, MockProvider
from app.security import current_user


@pytest.fixture
def config_client(monkeypatch):
    monkeypatch.setattr("app.ai_configuration.record", lambda *args: None)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    User.__table__.create(engine)
    AIConfiguration.__table__.create(engine)
    cfg = Settings(_env_file=None, model_mode="mock")
    monkeypatch.setattr("app.ai_configuration.settings", lambda: cfg)
    app = FastAPI()
    from fastapi.responses import JSONResponse

    from app.errors import AppError

    @app.exception_handler(AppError)
    async def error_handler(request, exc):
        return JSONResponse({"code": exc.code}, status_code=exc.status)

    app.include_router(router)
    user = SimpleNamespace(id=uuid.uuid4())
    app.dependency_overrides[current_user] = lambda: user

    def database():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = database
    with TestClient(app) as client:
        yield client, app, user, engine
    engine.dispose()


def test_account_isolation_key_retention_and_no_reset(config_client):
    client, app, user, engine = config_client
    body = {"mode": "cloud", "api_base": "https://models.example/v1", "model": "chat", "api_key": "secret"}
    assert client.get("/api/v1/ai-config").json()["mode"] == "default"
    result = client.put("/api/v1/ai-config", json=body)
    assert result.status_code == 200 and result.json()["has_api_key"]
    assert "secret" not in result.text and "secret" not in client.get("/api/v1/ai-config").text
    body.pop("api_key")
    assert client.put("/api/v1/ai-config", json=body).status_code == 200
    with Session(engine) as db:
        assert db.get(AIConfiguration, user.id).api_key == "secret"
    app.dependency_overrides[current_user] = lambda: SimpleNamespace(id=uuid.uuid4())
    assert client.get("/api/v1/ai-config").json()["mode"] == "default"
    app.dependency_overrides[current_user] = lambda: user
    body["api_base"] = "https://other.example/v1"
    assert client.put("/api/v1/ai-config", json=body).status_code == 422
    assert client.put("/api/v1/ai-config", json={"mode": "default"}).status_code == 422
    with Session(engine) as db:
        assert db.get(AIConfiguration, user.id).api_key == "secret"


def test_custom_model_and_connection_test_do_not_save(config_client, monkeypatch):
    client, _, user, engine = config_client
    seen = []

    async def reply(self, question, history):
        seen.append(self.chat_config)
        return SimpleNamespace(answer="你好")

    monkeypatch.setattr(CompatibleProvider, "general_answer", reply)
    body = {
        "mode": "cloud",
        "api_base": "https://models.example/v1",
        "model": "custom-chat",
        "api_key": "test-key",
    }
    assert client.post("/api/v1/ai-config/test", json=body).status_code == 200
    assert seen[0].llm_api_key == "test-key" and seen[0].llm_model == "custom-chat"
    assert client.get("/api/v1/ai-config").json()["mode"] == "default"
    assert client.put("/api/v1/ai-config", json=body).status_code == 200
    with Session(engine) as db:
        model = user_chat_provider(db, user.id)
        assert model.chat_config.llm_api_base == body["api_base"]
        assert isinstance(user_chat_provider(db, uuid.uuid4(), MockProvider), MockProvider)


@pytest.mark.parametrize(
    "base",
    [
        "file:///tmp",
        "https://key:secret@example.org/v1",
        "https://example.org?a=b",
        "https://example.org/#x",
        "https://example.org:not-a-port/v1",
        "https://example.org:65536/v1",
        "https://example.org:0/v1",
        "https://exa mple.org/v1",
        "https://example.org/\nadmin",
        "",
    ],
)
def test_invalid_model_addresses(base):
    with pytest.raises(ValidationError):
        AIConfigurationInput(mode="cloud", api_base=base, model="test")


@pytest.mark.asyncio
async def test_custom_chat_payload_and_embedding_configuration(monkeypatch):
    cfg = Settings(_env_file=None, model_mode="mock")
    original = cfg.model_dump()
    monkeypatch.setattr("app.ai_configuration.settings", lambda: cfg)
    row = AIConfiguration(
        mode="cloud",
        api_base="https://models.example/v1",
        model="custom-chat",
        api_key="test-key",
        api_style="openai",
    )
    model = configured_provider(row)
    captured = []

    async def request(base, key, path, payload):
        captured.append((base, key, path, payload))
        return {
            "choices": [
                {
                    "message": {"content": '{"answer":"你好","answerable":true,"sources":[]}'},
                    "finish_reason": "stop",
                }
            ]
        }

    monkeypatch.setattr(model, "request", request)
    assert (await model.general_answer("你好", [])).answer == "你好"
    base, key, path, payload = captured[0]
    assert base == row.api_base and key == "test-key" and path == "/chat/completions"
    assert payload["model"] == "custom-chat" and "reasoning_effort" not in payload
    assert cfg.model_dump() == original


def test_configuration_controls_chat_and_persists_model_mode(clients, monkeypatch):
    from test_integration import API, ask

    from app.schemas import Answer

    student, _, other = clients
    body = {
        "mode": "cloud",
        "api_base": "https://models.example/v1",
        "model": "custom-chat",
        "api_key": "test-key",
    }
    assert student.put(API + "/ai-config", json=body).status_code == 200
    assert other.get(API + "/ai-config").json()["mode"] == "default"
    seen = []

    async def reply(self, question, history):
        seen.append(self.chat_config.llm_model)
        return Answer(answer="自定义模型的回复", answerable=True, sources=[])

    monkeypatch.setattr(CompatibleProvider, "general_answer", reply)
    conversation, events = ask(student, "你好")
    assert seen == ["custom-chat"]
    assert events["answer"]["model_mode"] == "real"
    assert events["answer"]["content"] == "自定义模型的回复"
    history = student.get(API + f"/conversations/{conversation}").json()["messages"]
    assert history[-1]["model_mode"] == "real"
    assert student.put(API + "/ai-config", json={"mode": "default"}).status_code == 422
    _, events = ask(student, "你好")
    assert events["answer"]["model_mode"] == "real"


def test_local_mode_is_no_longer_accepted():
    with pytest.raises(ValidationError):
        AIConfigurationInput(mode="local", api_base="http://localhost:11434/v1", model="test")


def test_draft_releases_configuration_transaction_before_model_call(clients, monkeypatch):
    from test_integration import API, ask

    from app import main
    from app.schemas import DraftOutput

    student, _, _ = clients
    conversation, _ = ask(student, "你好")
    assert (
        student.put(
            API + "/ai-config",
            json={"api_base": "https://models.example/v1", "model": "chat", "api_key": "test-key"},
        ).status_code
        == 200
    )
    original = main.user_chat_provider
    captured = {}

    def resolve(db, *args):
        captured["db"] = db
        return original(db, *args)

    async def draft(self, history):
        assert not captured["db"].in_transaction()
        return DraftOutput(title="问题", category="其他", description="说明")

    monkeypatch.setattr(main, "user_chat_provider", resolve)
    monkeypatch.setattr(CompatibleProvider, "draft", draft)
    assert student.post(API + f"/conversations/{conversation}/ticket-draft").status_code == 200


@pytest.mark.parametrize("style", ["openai", "anthropic"])
def test_supported_interface_types(config_client, style):
    client, _, _, _ = config_client
    body = {
        "api_base": "https://models.example/v1",
        "model": "chat",
        "api_key": "test-key",
        "api_style": style,
    }
    response = client.put("/api/v1/ai-config", json=body)
    assert response.status_code == 200 and response.json()["api_style"] == style


@pytest.mark.parametrize("style", ["compatible", "deepseek"])
def test_removed_interface_types_are_rejected(style):
    with pytest.raises(ValidationError):
        AIConfigurationInput(api_base="https://models.example/v1", model="chat", api_style=style)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "base,path", [("https://models.example", "/v1/messages"), ("https://models.example/v1/", "/messages")]
)
async def test_anthropic_request_and_response(monkeypatch, base, path):
    cfg = Settings(_env_file=None, model_mode="mock")
    monkeypatch.setattr("app.ai_configuration.settings", lambda: cfg)
    row = AIConfiguration(
        mode="cloud", api_base=base, model="custom-claude", api_key="test-key", api_style="anthropic"
    )
    model = configured_provider(row)
    captured = []

    async def request(base, key, path, payload, headers=None):
        captured.append((base, key, path, payload, headers))
        return {
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": '{"answer":"hello","answerable":true,"sources":[]}'}],
        }

    monkeypatch.setattr(model, "request", request)
    assert (await model.general_answer("hello", [])).answer == "hello"
    target, key, actual_path, payload, headers = captured[0]
    assert target == base.rstrip("/") and actual_path == path
    assert key == "test-key" and headers == {"x-api-key": "test-key", "anthropic-version": "2023-06-01"}
    assert payload["model"] == "custom-claude" and payload["max_tokens"] == 4096
    assert payload["system"] and [m["role"] for m in payload["messages"]] == ["user"]
    assert "response_format" not in payload and "reasoning_effort" not in payload


@pytest.mark.asyncio
async def test_anthropic_truncated_response_is_rejected(monkeypatch):
    from app.errors import AppError

    cfg = Settings(_env_file=None, model_mode="mock")
    monkeypatch.setattr("app.ai_configuration.settings", lambda: cfg)
    row = AIConfiguration(
        mode="cloud",
        api_base="https://models.example",
        model="custom-claude",
        api_key="test-key",
        api_style="anthropic",
    )
    model = configured_provider(row)

    async def request(*args, **kwargs):
        return {"stop_reason": "max_tokens", "content": [{"type": "text", "text": '{"answer":'}]}

    monkeypatch.setattr(model, "request", request)
    with pytest.raises(AppError) as error:
        await model.general_answer("hello", [])
    assert error.value.code == "MODEL_OUTPUT_TRUNCATED"
