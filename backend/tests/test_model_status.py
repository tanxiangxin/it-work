from types import SimpleNamespace

from app.ai_configuration import ServerTestInput, configuration_status
from app.ai_configuration import test_server_configuration as check_server


def test_status_shows_feature_scope_without_credentials(monkeypatch):
    cfg = SimpleNamespace(
        model_mode="mock",
        llm_api_key="never-expose",
        llm_model="server-model",
        llm_api_style="deepseek",
        embedding_api_base="http://embedding",
        embedding_model="bge",
    )
    monkeypatch.setattr("app.ai_configuration.settings", lambda: cfg)
    db = SimpleNamespace(get=lambda *args: SimpleNamespace(model="personal-model", api_key="personal-secret"))
    result = configuration_status(SimpleNamespace(id="user", role="student"), db)
    assert not result["can_test_server"]
    assert result["features"][0]["source"] == "个人配置"
    assert result["features"][1]["mode"] == "mock"
    assert not result["features"][3]["configured"]
    assert "secret" not in str(result) and "never-expose" not in str(result)


async def test_mock_server_check_never_calls_cloud(monkeypatch):
    monkeypatch.setattr("app.ai_configuration.settings", lambda: SimpleNamespace(model_mode="mock"))
    monkeypatch.setattr("app.ai_configuration.provider", lambda: (_ for _ in ()).throw(AssertionError()))
    result = await check_server(ServerTestInput(kind="chat"), SimpleNamespace(role="admin"))
    assert result["mode"] == "mock"


def test_only_admin_can_probe_server_model(clients):
    student, admin, _ = clients
    assert student.post("/api/v1/ai-config/server-test", json={"kind": "chat"}).status_code == 403
    result = admin.post("/api/v1/ai-config/server-test", json={"kind": "embedding"})
    assert result.status_code == 200 and result.json()["mode"] == "mock"
