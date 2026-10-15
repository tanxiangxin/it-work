import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from redis import Redis
from redis.exceptions import ConnectionError
from starlette.requests import Request

from app.config import Settings
from app.errors import AppError
from app.usage import ADMIT, UsageLeaseMiddleware, begin_request, request_kind, usage_summary


@pytest.mark.parametrize(
    "price", [{"input": -1, "output": 1}, {"input": float("inf"), "output": 1}, {"input": 1}]
)
def test_prices_require_finite_complete_nonnegative_rates(price):
    with pytest.raises(ValueError):
        Settings(_env_file=None, model_prices={"model": price})


@pytest.fixture
def limits_redis():
    url = os.environ.get("TEST_REDIS_URL")
    if not url:
        pytest.skip("Requires dedicated test Redis")
    client = Redis.from_url(url)
    prefix = "test-limits:" + uuid.uuid4().hex
    yield client, [prefix + suffix for suffix in (":minute", ":day", ":active")]
    for key in client.scan_iter(prefix + "*"):
        client.delete(key)


def admit(client, keys, token, minute=100, daily=100, concurrent=2):
    return client.eval(
        ADMIT, 3, *keys, time.time(), token, minute, daily, concurrent, 86400, time.time() + 3600
    )


def test_parallel_admission_never_exceeds_user_slots(limits_redis):
    client, keys = limits_redis
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(lambda i: admit(client, keys, str(i)), range(30)))
    assert results.count(0) == 2
    assert client.zcard(keys[2]) == 2
    assert int(client.get(keys[1])) == 2  # Rejected attempts do not consume quota.
    token = client.zrange(keys[2], 0, 0)[0]
    client.zrem(keys[2], token)
    assert admit(client, keys, "next") == 0


def test_daily_quota_and_expired_lease(limits_redis):
    client, keys = limits_redis
    client.zadd(keys[2], {"crashed-request": time.time() - 1})
    assert admit(client, keys, "first", daily=1) == 0
    client.zrem(keys[2], "first")
    assert admit(client, keys, "second", daily=1) == 2
    assert client.zscore(keys[2], "crashed-request") is None
    assert 0 < client.ttl(keys[1]) <= 86400


def test_limits_fail_closed_if_redis_unavailable(monkeypatch):
    cfg = Settings(_env_file=None, rate_limit_enabled=True)
    monkeypatch.setattr("app.usage.settings", lambda: cfg)
    monkeypatch.setattr(
        "app.usage.redis_client",
        lambda: SimpleNamespace(eval=lambda *args: (_ for _ in ()).throw(ConnectionError())),
    )
    request = Request(
        {"type": "http", "path": "/api/v1/conversations/1/messages", "method": "POST", "headers": []}
    )
    db = SimpleNamespace(scalar=lambda query: 0, execute=lambda *args: None)
    with pytest.raises(AppError) as error:
        begin_request(request, SimpleNamespace(id=uuid.uuid4()), db)
    assert error.value.code == "LIMITS_UNAVAILABLE"


async def test_stream_disconnect_releases_only_its_lease(monkeypatch):
    released = []
    monkeypatch.setattr(
        "app.usage.redis_client", lambda: SimpleNamespace(zrem=lambda *args: released.append(args))
    )

    async def stream(scope, receive, send):
        scope["state"]["quota_lease"] = ("user-slots", "this-request")
        raise RuntimeError("disconnect")

    with pytest.raises(RuntimeError):
        await UsageLeaseMiddleware(stream)({"type": "http", "state": {}}, None, None)
    assert released == [("user-slots", "this-request")]


def test_cost_is_unknown_when_usage_or_price_missing(monkeypatch):
    cfg = Settings(_env_file=None, model_prices={"priced": {"input": 2, "output": 4}})
    monkeypatch.setattr("app.usage.settings", lambda: cfg)
    monkeypatch.setattr("app.usage.redis_client", lambda: SimpleNamespace(get=lambda key: b"3"))
    rows = [
        SimpleNamespace(
            model="priced", calls=1, usage={"prompt_tokens": 1000000, "completion_tokens": 500000}
        ),
        SimpleNamespace(model="unpriced", calls=1, usage={"input_tokens": 10, "output_tokens": 5}),
        SimpleNamespace(model="missing", calls=1, usage=None),
    ]
    result = usage_summary(
        SimpleNamespace(scalars=lambda query: SimpleNamespace(all=lambda: rows)), uuid.uuid4()
    )
    assert result["remaining"] == 197
    assert result["models"][0]["estimated_cny"] == 4
    assert result["models"][1]["estimated_cny"] is None
    assert result["models"][2]["unreported_usage"] == 1


def test_usage_cannot_select_another_account(clients):
    from app import models as m
    from app.db import session

    student, admin, _ = clients
    student_id = uuid.UUID(student.get("/api/v1/auth/me").json()["id"])
    admin_id = uuid.UUID(admin.get("/api/v1/auth/me").json()["id"])
    with session() as db:
        for id, model in [(student_id, "student-model"), (admin_id, "private-admin-model")]:
            db.add(
                m.RequestTrace(
                    request_id=str(uuid.uuid4()),
                    user_id=id,
                    model=model,
                    model_mode="real",
                    duration_ms=1,
                    calls=1,
                    status="complete",
                    usage={"prompt_tokens": 10, "completion_tokens": 5},
                )
            )
        db.commit()
    own = student.get("/api/v1/usage").json()
    other = student.get("/api/v1/usage", params={"user_id": admin.get("/api/v1/auth/me").json()["id"]}).json()
    assert own["models"] == other["models"]
    assert [row["model"] for row in own["models"]] == ["student-model"]
    assert "api_key" not in str(own)


def test_live_auth_admission_and_lease_release(clients, monkeypatch):
    from app.config import settings

    student, _, _ = clients
    cfg = settings()
    monkeypatch.setattr(cfg, "rate_limit_enabled", True)
    monkeypatch.setattr(cfg, "redis_url", os.environ["TEST_REDIS_URL"])
    monkeypatch.setattr(cfg, "ai_daily_requests", 1)
    conversation = student.post("/api/v1/conversations").json()["id"]
    path = f"/api/v1/conversations/{conversation}/messages"
    first = student.post(path, json={"content": "你好"})
    assert first.status_code == 200
    assert "event: done" in first.text
    second = student.post(path, json={"content": "你好"})
    assert second.status_code == 429 and second.json()["code"] == "DAILY_QUOTA"
    assert second.headers["Retry-After"] == "60"
    user_id = student.get("/api/v1/auth/me").json()["id"]
    assert Redis.from_url(os.environ["TEST_REDIS_URL"]).zcard(f"limits:active:{user_id}") == 0


def test_model_trace_does_not_block_on_admission_lock(clients, monkeypatch):
    from app.config import settings

    _, admin, _ = clients
    monkeypatch.setattr(settings(), "rate_limit_enabled", True)
    monkeypatch.setattr(settings(), "redis_url", os.environ["TEST_REDIS_URL"])
    response = admin.post(
        "/api/v1/announcements/extract", json={"content": "校园测试通知：明天下午办理校园网络业务。"}
    )
    assert response.status_code == 200, response.text


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/conversations/1/ticket-draft",
        "/api/v1/courses/1/study-jobs",
        "/api/v1/courses/1/study/2/grade-jobs",
        "/api/v1/courses/1/material-search",
        "/api/v1/study-jobs/1/retry",
    ],
)
def test_expensive_routes_are_covered(path):
    assert request_kind(path, "POST") == "ai"
    assert request_kind(path, "GET") is None
