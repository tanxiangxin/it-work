import socket
from types import SimpleNamespace

import httpx
import pytest

from app.errors import AppError
from app.provider_network import public_model_target
from app.providers import CompatibleProvider


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "host", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "[::1]", "[::ffff:127.0.0.1]", "224.0.0.1"]
)
async def test_custom_cloud_models_cannot_access_private_addresses(host):
    with pytest.raises(AppError) as error:
        await public_model_target(f"http://{host}/v1/chat/completions", 1)
    assert error.value.code == "MODEL_ADDRESS_BLOCKED"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 307])
async def test_pinned_requests_keep_tls_identity_and_do_not_follow_redirects(monkeypatch, status):
    captured = {}

    async def target(*args):
        return httpx.URL("https://8.8.8.8/v1/chat/completions"), "models.example", "models.example"

    class Client:
        def __init__(self, **kwargs):
            captured["options"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, **kwargs):
            captured.update(url=str(url), request=kwargs)
            return httpx.Response(status, json={"choices": []})

    monkeypatch.setattr("app.providers.public_model_target", target)
    monkeypatch.setattr(httpx, "AsyncClient", Client)
    model = CompatibleProvider(chat_config=SimpleNamespace())
    if status == 307:
        with pytest.raises(AppError) as error:
            await model.request("https://models.example/v1", "private-key", "/chat/completions", {})
        assert error.value.code == "MODEL_CONFIGURATION"
    else:
        assert await model.request("https://models.example/v1", "private-key", "/chat/completions", {}) == {
            "choices": []
        }
    assert captured["url"] == "https://8.8.8.8/v1/chat/completions"
    assert captured["request"]["headers"] == {"Host": "models.example", "Authorization": "Bearer private-key"}
    assert captured["request"]["extensions"]["sni_hostname"] == "models.example"
    assert captured["options"]["trust_env"] is False and captured["options"]["follow_redirects"] is False


@pytest.mark.asyncio
async def test_dns_target_is_pinned_and_original_host_preserved(monkeypatch):
    calls = []

    async def resolve(host, port, **kwargs):
        calls.append((host, port))
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", port))]

    monkeypatch.setattr(
        "asyncio.base_events.BaseEventLoop.getaddrinfo",
        lambda self, *args, **kwargs: resolve(*args, **kwargs),
    )
    target, host, hostname = await public_model_target("https://models.example:8443/v1/messages", 1)
    assert str(target) == "https://8.8.8.8:8443/v1/messages"
    assert host == "models.example:8443" and hostname == "models.example"
    assert calls == [("models.example", 8443)]


@pytest.mark.asyncio
async def test_mixed_dns_answers_cannot_bypass_network_boundary(monkeypatch):
    async def resolve(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (host, 443)) for host in ["8.8.8.8", "127.0.0.1"]]

    monkeypatch.setattr(
        "asyncio.base_events.BaseEventLoop.getaddrinfo",
        lambda self, *args, **kwargs: resolve(*args, **kwargs),
    )
    with pytest.raises(AppError) as error:
        await public_model_target("https://models.example/v1", 1)
    assert error.value.code == "MODEL_ADDRESS_BLOCKED"
