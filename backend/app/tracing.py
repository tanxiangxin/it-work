import time

from app.config import settings
from app.db import session
from app.models import RequestTrace


def record(request_id, user_id, operation, model, started, status, embedding=False):
    cfg = settings() if embedding else getattr(model, "chat_config", None) or settings()
    with session() as db:
        db.add(
            RequestTrace(
                request_id=str(request_id),
                user_id=user_id,
                operation=operation,
                model_mode=cfg.model_mode,
                model=(
                    "mock"
                    if cfg.model_mode == "mock"
                    else cfg.embedding_model
                    if embedding
                    else cfg.llm_model
                ),
                duration_ms=int((time.monotonic() - started) * 1000),
                calls=model.calls,
                usage=model.usage,
                status=status,
            )
        )
        db.commit()
