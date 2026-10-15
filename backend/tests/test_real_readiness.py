import json

import pytest

from app.config import Settings
from app.errors import AppError
from app.evaluation import inspect_events, parse_sse, summarize
from app.model_check import check_models
from app.providers import CompatibleProvider
from app.schemas import Answer


def real_config(**changes):
    values = dict(
        model_mode="real",
        llm_api_base="https://api.openai.com/v1",
        llm_api_key="test-secret",
        llm_model="gpt-6.1-sol",
        llm_api_style="openai",
        llm_thinking_enabled=False,
        embedding_requires_api_key=True,
        embedding_revision="",
        embedding_send_dimensions=True,
        embedding_api_base="https://api.openai.com/v1",
        embedding_api_key="test-secret",
        embedding_model="text-embedding-3-small",
        llm_reasoning_effort="low",
        llm_max_completion_tokens=4096,
    )
    return Settings(_env_file=None, **(values | changes))


@pytest.mark.asyncio
async def test_sol_chat_contract_and_embedding_dimensions(monkeypatch):
    cfg = real_config()
    monkeypatch.setattr("app.providers.settings", lambda: cfg)
    requests = []

    async def request(base, key, path, payload):
        requests.append((path, payload))
        if path == "/embeddings":
            return {"data": [{"index": 0, "embedding": [1.0] * 1024}]}
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({"answer": "IT-1024", "answerable": True, "sources": [1]})
                    }
                }
            ]
        }

    provider = CompatibleProvider()
    monkeypatch.setattr(provider, "request", request)
    assert len((await provider.embed(["VPN"]))[0]) == 1024
    await provider.structured("system", {}, Answer)
    assert requests[0][1]["model"] == "text-embedding-3-small"
    assert requests[0][1]["dimensions"] == 1024
    chat = requests[1][1]
    assert chat["model"] == "gpt-6.1-sol" and chat["reasoning_effort"] == "low"
    assert "temperature" not in chat and chat["max_completion_tokens"] == 4096


@pytest.mark.parametrize("effort", ["none", "minimal"])
def test_sol_rejects_unsupported_reasoning(effort):
    with pytest.raises(ValueError):
        real_config(llm_reasoning_effort=effort)


@pytest.mark.asyncio
@pytest.mark.parametrize("thinking", [False, True])
async def test_deepseek_chat_parameter_dialect(monkeypatch, thinking):
    cfg = real_config(
        llm_model="deepseek-v4.1-flash", llm_api_style="deepseek", llm_thinking_enabled=thinking
    )
    monkeypatch.setattr("app.providers.settings", lambda: cfg)
    captured = {}

    async def request(base, key, path, payload):
        captured.update(payload)
        return {"choices": [{"message": {"content": '{"answer":"test","answerable":false,"sources":[]}'}}]}

    provider = CompatibleProvider()
    monkeypatch.setattr(provider, "request", request)
    await provider.structured("Output JSON", {}, Answer)
    assert captured["model"] == "deepseek-v4.1-flash"
    assert captured["max_tokens"] == 4096 and "max_completion_tokens" not in captured
    assert captured["thinking"] == {"type": "enabled" if thinking else "disabled"}
    assert captured["response_format"] == {"type": "json_object"}
    if thinking:
        assert captured["reasoning_effort"] == "low" and "temperature" not in captured
    else:
        assert captured["temperature"] == 0 and "reasoning_effort" not in captured


def test_deepseek_conflicting_thinking_configuration():
    with pytest.raises(ValueError):
        real_config(
            llm_model="deepseek-v4.1-flash",
            llm_api_style="deepseek",
            llm_thinking_enabled=True,
            llm_reasoning_effort="none",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("send_dimensions", [False, True])
async def test_deepseek_embedding_keeps_id_and_validates_actual_dimensions(monkeypatch, send_dimensions):
    cfg = real_config(embedding_model="deepseek-embedding", embedding_send_dimensions=send_dimensions)
    monkeypatch.setattr("app.providers.settings", lambda: cfg)
    dimension = 1024

    async def request(base, key, path, payload):
        assert path == "/embeddings" and payload["model"] == "deepseek-embedding"
        assert ("dimensions" in payload) is send_dimensions
        if send_dimensions:
            assert payload["dimensions"] == 1024
        return {"data": [{"index": 0, "embedding": [1.0] * dimension}]}

    provider = CompatibleProvider()
    monkeypatch.setattr(provider, "request", request)
    assert len((await provider.embed(["VPN"]))[0]) == 1024
    dimension = 1536
    with pytest.raises(AppError) as exc:
        await provider.embed(["VPN"])
    assert exc.value.code == "EMBEDDING_OUTPUT"


@pytest.mark.parametrize(
    "base", ["ftp://host", "https://user:secret@host/v1", "https://host/v1?api_key=secret"]
)
def test_real_base_rejects_invalid_and_secret_urls(base):
    with pytest.raises(ValueError) as exc:
        real_config(llm_api_base=base)
    assert "test-secret" not in str(exc.value) and "api_key=secret" not in str(exc.value)


@pytest.mark.asyncio
async def test_preflight_is_offline_and_does_not_expose_keys(monkeypatch):
    def forbidden():
        raise AssertionError("offline preflight must not instantiate a provider")

    monkeypatch.setattr("app.model_check.CompatibleProvider", forbidden)
    report = await check_models(real_config())
    assert report["status"] == "configured" and not report["network_verified"]
    assert "test-secret" not in json.dumps(report)
    cfg = Settings(_env_file=None, llm_api_key="", embedding_api_key="")
    assert (await check_models(cfg))["status"] == "incomplete"


@pytest.mark.asyncio
async def test_online_check_refuses_mock_without_network(monkeypatch):
    cfg = real_config().model_copy(update={"model_mode": "mock"})
    monkeypatch.setattr(
        "app.model_check.CompatibleProvider", lambda: pytest.fail("mock must not call real providers")
    )
    assert (await check_models(cfg, online=True))["status"] == "real_mode_required"


def answer_events(answerable=True, mode="real"):
    return [
        {
            "event": "answer",
            "data": {
                "answer_id": "answer",
                "model_mode": mode,
                "content": "示例",
                "answerable": answerable,
                "citations": [{"chunk_id": "chunk", "version_id": "version", "document_name": "vpn.md"}]
                if answerable
                else [],
            },
        },
        {"event": "done", "data": {}},
    ]


def test_sse_crlf_multiline_and_evaluation_contract():
    lines = [
        b": heartbeat\r\n",
        b"event: status\r\n",
        b"data: {\r\n",
        b'data: "stage": "retrieval"}\r\n',
        b"\r\n",
    ]
    assert list(parse_sse(lines)) == [{"event": "status", "data": {"stage": "retrieval"}}]
    case = {"answerable": True, "expected_document": "vpn.md"}
    result = inspect_events(case, answer_events())
    assert result["status"] == "complete" and result["expected_document_cited"]
    assert inspect_events(case, answer_events(mode="mock"))["code"] == "NON_REAL_ANSWER"
    assert inspect_events(case, answer_events()[:-1])["code"] == "INCOMPLETE_SSE"


def test_model_failure_is_not_refusal_or_accuracy():
    case = {"answerable": False}
    failure = inspect_events(
        case, [{"event": "error", "data": {"code": "MODEL_TIMEOUT"}}, {"event": "done", "data": {}}]
    )
    assert failure["status"] == "model_failure" and "answerability_match" not in failure
    refusal = inspect_events(case, answer_events(answerable=False)) | {"elapsed_ms": 100}
    summary = summarize([failure, refusal])
    assert summary["failures"] == 1 and summary["answerability_matches"] == 1
    assert summary["completed_latency_ms"]["median"] == 100
    assert summary["human_answer_accuracy"] is None and summary["cost"] is None


def test_completed_protocol_is_not_a_quality_pass():
    summary = summarize(
        [
            {
                "status": "complete",
                "elapsed_ms": 1,
                "answerability_match": False,
                "expected_document_cited": False,
                "citations_verified": True,
            }
        ]
    )
    assert summary["failures"] == 0
    assert summary["expectation_failures"] == 1


@pytest.mark.asyncio
async def test_local_bge_no_key_required_or_forwarded(monkeypatch):
    cfg = real_config(
        embedding_api_base="http://embedding:80/v1",
        embedding_model="BAAI/bge-m3",
        embedding_requires_api_key=False,
        embedding_api_key="old-provider-secret",
        embedding_send_dimensions=False,
        embedding_revision="pinned-model-revision",
    )
    without_key = real_config(
        **{
            name: getattr(cfg, name)
            for name in (
                "embedding_api_base",
                "embedding_model",
                "embedding_requires_api_key",
                "embedding_send_dimensions",
                "embedding_revision",
            )
        },
        embedding_api_key="",
    )
    assert (await check_models(without_key))["status"] == "configured"
    monkeypatch.setattr("app.providers.settings", lambda: cfg)

    async def request(base, key, path, payload):
        assert key == "" and base == "http://embedding:80/v1"
        assert payload == {"model": "BAAI/bge-m3", "input": ["校园 VPN"]}
        return {"data": [{"index": 0, "embedding": [1.0] * 1024}]}

    model = CompatibleProvider()
    monkeypatch.setattr(model, "request", request)
    assert len((await model.embed(["校园 VPN"]))[0]) == 1024
    changed_revision = cfg.model_copy(update={"embedding_revision": "new-model-revision"})
    assert cfg.index_key != changed_revision.index_key
