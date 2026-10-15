"""User admission limits shared by API processes; usage totals come from persisted traces."""

import asyncio
import hashlib
import re
import time
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import func, or_, select, text

from app import models as m
from app.config import settings
from app.db import get_db
from app.errors import AppError
from app.security import current_user

router = APIRouter(prefix="/api/v1/usage", tags=["Usage"])
ZONE = ZoneInfo("Asia/Shanghai")

# Check all limits before incrementing anything. Lease tokens prevent one request
# from releasing another's slot; expired leases are reclaimed after a process crash.
ADMIT = """
redis.call('ZREMRANGEBYSCORE', KEYS[3], '-inf', ARGV[1])
if tonumber(redis.call('GET', KEYS[1]) or '0') >= tonumber(ARGV[3]) then return 1 end
if tonumber(redis.call('GET', KEYS[2]) or '0') >= tonumber(ARGV[4]) then return 2 end
if redis.call('ZCARD', KEYS[3]) >= tonumber(ARGV[5]) then return 3 end
redis.call('INCR', KEYS[1]); redis.call('EXPIRE', KEYS[1], 120)
redis.call('INCR', KEYS[2]); redis.call('EXPIRE', KEYS[2], ARGV[6])
redis.call('ZADD', KEYS[3], ARGV[7], ARGV[2]); redis.call('EXPIRE', KEYS[3], 3600)
return 0
"""
LOGIN = """
for i=1,2 do
  if tonumber(redis.call('GET', KEYS[i]) or '0') >= tonumber(ARGV[i]) then return 1 end
end
for i=1,2 do redis.call('INCR', KEYS[i]); redis.call('EXPIRE', KEYS[i], 120) end
return 0
"""


def redis_client():
    return Redis.from_url(settings().redis_url, socket_connect_timeout=2, socket_timeout=2)


def request_kind(path, method):
    if method != "POST":
        return None
    if re.fullmatch(
        r"/api/v1/(?:documents|documents/[^/]+/(?:versions|retry)|courses/[^/]+/documents(?:/[^/]+/(?:versions|retry))?)",
        path,
    ):
        return "upload"
    if (
        re.fullmatch(r"/api/v1/conversations/[^/]+/(?:messages|ticket-draft)", path)
        or re.fullmatch(
            r"/api/v1/courses/[^/]+/(?:study|study-jobs|material-search|material-organization|study/[^/]+/(?:submit|grade-jobs))",
            path,
        )
        or re.fullmatch(r"/api/v1/study-jobs/[^/]+/retry", path)
        or path
        in {
            "/api/v1/announcements/extract",
            "/api/v1/ai-config/test",
            "/api/v1/ai-config/server-test",
            "/api/v1/retrieval/compare",
        }
    ):
        return "ai"
    return None


def login_limit(request, email):
    cfg = settings()
    if not cfg.rate_limit_enabled:
        return
    minute = int(time.time()) // 60
    peer = request.client.host if request.client else "unknown"
    keys = [
        f"limits:login:{minute}:" + hashlib.sha256(value.encode()).hexdigest()
        for value in ("peer:" + peer, "account:" + email.lower().strip())
    ]
    try:
        denied = redis_client().eval(LOGIN, 2, *keys, cfg.login_per_minute, cfg.login_account_per_minute)
    except RedisError:
        raise AppError("LIMITS_UNAVAILABLE", "登录保护暂不可用，请稍后重试", 503) from None
    if denied:
        raise AppError("RATE_LIMIT", "登录尝试过于频繁，请稍后重试", 429)


def begin_request(request, user, db):
    cfg = settings()
    kind = request_kind(request.url.path, request.method)
    if not cfg.rate_limit_enabled or not kind or getattr(request.state, "quota_lease", None):
        return
    # Serialize admission with job creation across courses and API processes.
    # Advisory locks serialize submissions without blocking foreign-key checks in
    # the separate trace-writing transaction used by synchronous model endpoints.
    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": "limits:" + str(user.id)}
    )
    active_study = db.scalar(
        select(func.count())
        .select_from(m.StudyJob)
        .where(m.StudyJob.user_id == user.id, m.StudyJob.status.in_(["queued", "running"]))
    )
    active_search = db.scalar(
        select(func.count())
        .select_from(m.MaterialSearch)
        .where(
            m.MaterialSearch.user_id == user.id,
            m.MaterialSearch.status.in_(["queued", "generating", "importing"]),
        )
    )
    import_owner = m.Document.owner_id == user.id
    if getattr(user, "role", "student") == "admin":
        import_owner = or_(import_owner, m.Document.owner_id.is_(None))
    active_import = db.scalar(
        select(func.count())
        .select_from(m.ImportJob)
        .join(m.DocumentVersion)
        .join(m.Document)
        .where(
            import_owner,
            m.ImportJob.status.in_(["queued", "parsing", "chunking", "embedding"]),
        )
    )
    if active_study + active_search + active_import >= cfg.user_active_jobs:
        raise AppError("ACTIVE_JOB_LIMIT", "进行中的任务已达上限，请等待完成后再提交", 429)
    stamp = datetime.now(ZONE)
    expires = (
        int(
            (
                (stamp + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0) - stamp
            ).total_seconds()
        )
        + 60
    )
    token = uuid.uuid4().hex
    lease = f"limits:active:{user.id}"
    minute_key = f"limits:{kind}:{user.id}:{int(time.time()) // 60}"
    day_key = f"limits:day:{kind}:{user.id}:{stamp.date()}"
    try:
        result = redis_client().eval(
            ADMIT,
            3,
            minute_key,
            day_key,
            lease,
            time.time(),
            token,
            cfg.ai_per_minute if kind == "ai" else cfg.upload_per_minute,
            cfg.ai_daily_requests if kind == "ai" else cfg.upload_per_minute * 60,
            cfg.user_concurrent_requests,
            expires,
            time.time() + 3600,
        )
    except RedisError:
        raise AppError("LIMITS_UNAVAILABLE", "用量保护暂不可用，请稍后重试", 503) from None
    if result:
        messages = {
            1: "请求过于频繁，请稍后重试",
            2: "今日调用额度已用完，明日重置",
            3: "同时处理的请求已达上限，请稍后重试",
        }
        raise AppError("DAILY_QUOTA" if result == 2 else "RATE_LIMIT", messages[result], 429)
    request.state.quota_lease = (lease, token)


class UsageLeaseMiddleware:
    """Release the slot after the entire SSE response, including disconnect/error paths."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        try:
            await self.app(scope, receive, send)
        finally:
            lease = scope.get("state", {}).get("quota_lease")
            if lease:
                try:
                    await asyncio.to_thread(redis_client().zrem, *lease)
                except RedisError:
                    pass  # Slot is reclaimed by its expiry if Redis is unavailable.


def usage_summary(db, user_id):
    cfg = settings()
    today = datetime.now(ZONE).replace(hour=0, minute=0, second=0, microsecond=0)
    rows = db.scalars(
        select(m.RequestTrace).where(m.RequestTrace.user_id == user_id, m.RequestTrace.created_at >= today)
    ).all()
    models = {}
    for row in rows:
        item = models.setdefault(
            row.model,
            {
                "model": row.model,
                "requests": 0,
                "calls": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "unreported_usage": 0,
                "estimated_cny": None,
            },
        )
        item["requests"] += 1
        item["calls"] += row.calls
        usage = row.usage or {}
        input_count = usage.get("prompt_tokens", usage.get("input_tokens"))
        output_count = usage.get("completion_tokens", usage.get("output_tokens"))
        if not isinstance(input_count, (int, float)) or not isinstance(output_count, (int, float)):
            item["unreported_usage"] += 1
        else:
            item["input_tokens"] += input_count
            item["output_tokens"] += output_count
    for item in models.values():
        price = cfg.model_prices.get(item["model"])
        if price and {"input", "output"}.issubset(price) and not item["unreported_usage"]:
            item["estimated_cny"] = round(
                (
                    item["input_tokens"] * max(0, price.get("input", 0))
                    + item["output_tokens"] * max(0, price.get("output", 0))
                )
                / 1_000_000,
                6,
            )
    try:
        count = int(redis_client().get(f"limits:day:ai:{user_id}:{today.date()}") or 0)
    except RedisError:
        count = None
    return {
        "date": str(today.date()),
        "timezone": "Asia/Shanghai",
        "enabled": cfg.rate_limit_enabled,
        "daily_limit": cfg.ai_daily_requests,
        "daily_used": count,
        "remaining": max(0, cfg.ai_daily_requests - count) if count is not None else None,
        "concurrent_limit": cfg.user_concurrent_requests,
        "active_job_limit": cfg.user_active_jobs,
        "models": list(models.values()),
        "cost_note": "按管理员配置的每百万 Token 人民币单价估算；缺少单价或 Token 用量时不估算。未包含供应商独立收取的搜索费用。",
    }


@router.get("")
def read_usage(user=Depends(current_user), db=Depends(get_db)):
    return usage_summary(db, user.id)
