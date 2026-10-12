"""Explicit real-provider preflight. Offline by default; never changes model mode or indexes."""

import argparse
import asyncio
import json
import time

from pydantic import ValidationError

from app.config import Settings, settings
from app.errors import AppError
from app.providers import CompatibleProvider

REQUIRED = (
    "llm_api_base",
    "llm_api_key",
    "llm_model",
    "embedding_api_base",
    "embedding_api_key",
    "embedding_model",
)


async def check_models(cfg: Settings, online=False):
    missing = [
        field.upper()
        for field in REQUIRED
        if not (field == "embedding_api_key" and not cfg.embedding_requires_api_key)
        and not getattr(cfg, field).strip()
    ]
    report = {"online": online, "active_mode": cfg.model_mode, "missing": missing, "status": "incomplete"}
    if missing:
        return report
    try:
        target = Settings(**(cfg.model_dump() | {"model_mode": "real"}))
    except ValidationError:
        return report | {"status": "invalid_configuration"}
    report.update(
        chat_model=target.llm_model, embedding_model=target.embedding_model, index_key=target.index_key
    )
    if not online:
        return report | {"status": "configured", "network_verified": False}
    if cfg.model_mode != "real":
        return report | {"status": "real_mode_required", "network_verified": False}
    model = CompatibleProvider()
    started = time.monotonic()
    try:
        vectors = await model.embed(["校园 VPN 错误 809", "忘记校园账号密码"])
        answer = await model.answer(
            "测试窗口编号是什么？",
            [
                {
                    "number": 1,
                    "document_name": "接入探针",
                    "heading": "测试",
                    "content": "测试窗口编号为 IT-1024。",
                }
            ],
            [],
        )
        if not answer.answerable or answer.sources != [1] or "IT-1024" not in answer.answer:
            raise AppError("PROBE_EVIDENCE", "探针回答未遵守证据与引用约束", 502)
        report.update(status="passed", network_verified=True, vectors=len(vectors), dimensions=1024)
    except AppError as exc:
        report.update(status="failed", code=exc.code, message=exc.message)
    report.update(calls=model.calls, usage=model.usage, elapsed_ms=round((time.monotonic() - started) * 1000))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--online", action="store_true", help="Send two embedding inputs and one chat request; may incur cost"
    )
    args = parser.parse_args()
    try:
        report = asyncio.run(check_models(settings(), args.online))
    except ValidationError:
        report = {
            "status": "invalid_configuration",
            "message": "Check backend model configuration; secrets are omitted.",
        }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["status"] in {"configured", "passed"} else 2)


if __name__ == "__main__":
    main()
