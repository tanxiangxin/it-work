import asyncio
import hashlib
import json
import logging
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from typing import Annotated, Literal

from argon2.exceptions import VerificationError, VerifyMismatchError
from fastapi import Depends, FastAPI, File, Form, Header, Query, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from redis import Redis
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException

from app import models as m
from app.ai_configuration import router as ai_configuration_router
from app.ai_configuration import user_chat_provider
from app.config import settings
from app.conversation import forced_route
from app.db import get_db, session
from app.errors import AppError
from app.jobs import ACTIVE, enqueue
from app.notifications import notify_ticket
from app.providers import provider
from app.retrieval import allowed_query, retrieve_with_vector
from app.schemas import (
    LoginInput,
    RetrievalCompareInput,
    StatusInput,
    TextInput,
    TicketInput,
    VisibilityInput,
)
from app.security import admin, current_user, make_session, passwords, token_hash
from app.storage import storage
from app.usage import UsageLeaseMiddleware, login_limit
from app.usage import router as usage_router

logger = logging.getLogger("campus")


@asynccontextmanager
async def lifespan(app):
    settings()  # Fail fast on invalid real-mode configuration.
    yield


app = FastAPI(title="校园 IT 服务台", version="0.1.0", lifespan=lifespan)
app.include_router(ai_configuration_router)
app.include_router(usage_router)
app.add_middleware(UsageLeaseMiddleware)
API = "/api/v1"


def error_response(request, status, code, message):
    return JSONResponse(
        {"code": code, "message": message, "request_id": getattr(request.state, "request_id", "")},
        status_code=status,
    )


@app.middleware("http")
async def request_context(request, call_next):
    request.state.request_id = str(uuid.uuid4())
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") != settings().public_origin.rstrip("/"):
            return error_response(request, 403, "INVALID_ORIGIN", "请求来源不允许")
        if request.headers.get("sec-fetch-site") == "cross-site":
            return error_response(request, 403, "INVALID_ORIGIN", "不允许跨站请求")
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(AppError)
async def app_error(request, exc):
    response = error_response(request, exc.status, exc.code, exc.message)
    if exc.status == 429:
        response.headers["Retry-After"] = "60"
    return response


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    return error_response(request, 422, "VALIDATION_ERROR", "输入格式或长度不符合要求")


@app.exception_handler(HTTPException)
async def http_error(request, exc):
    return error_response(request, exc.status_code, "HTTP_ERROR", "请求无效或资源不存在")


@app.exception_handler(Exception)
async def unexpected_error(request, exc):
    logger.error("request_failed request=%s type=%s", request.state.request_id, type(exc).__name__)
    return error_response(request, 500, "INTERNAL_ERROR", "服务异常，请使用请求编号联系管理员")


def dump(record, *fields):
    return {
        key: str(value) if isinstance(value := getattr(record, key), uuid.UUID) else value
        for key in ("id", "created_at", *fields)
    }


def user_data(user):
    return dump(user, "email", "name", "role")


def page_result(db, query, page, size, render, order=None):
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(
        query.order_by(None)
        .order_by(
            *(
                order
                or (
                    query.column_descriptions[0]["entity"].created_at.desc(),
                    query.column_descriptions[0]["entity"].id,
                )
            )
        )
        .offset((page - 1) * size)
        .limit(size)
    ).all()
    return {"items": [render(row) for row in rows], "total": total, "page": page, "page_size": size}


Page = Annotated[int, Query(ge=1)]
Size = Annotated[int, Query(ge=1, le=100)]


def document_detail(db, doc):
    versions = db.scalars(
        select(m.DocumentVersion)
        .where(m.DocumentVersion.document_id == doc.id)
        .order_by(m.DocumentVersion.created_at.desc(), m.DocumentVersion.id)
    ).all()
    data = dump(doc, "name", "visibility", "active_version_id", "deleted")
    data["versions"] = []
    for v in versions:
        job = db.scalar(select(m.ImportJob).where(m.ImportJob.version_id == v.id))
        data["versions"].append(
            {
                **dump(v, "filename", "status", "error", "index_key"),
                "job_id": str(job.id) if job else None,
                "chunks": db.scalar(
                    select(func.count()).select_from(m.Chunk).where(m.Chunk.version_id == v.id)
                ),
            }
        )
    return data


def conversation_owned(db, id, user, lock=False):
    q = select(m.Conversation).where(
        m.Conversation.id == id, m.Conversation.user_id == user.id, m.Conversation.history_hidden.is_(False)
    )
    conversation = db.scalar(q.with_for_update() if lock else q)
    if not conversation:
        raise AppError("NOT_FOUND", "会话不存在", 404)
    return conversation


def ticket_owned(db, id, user, lock=False):
    q = select(m.Ticket).where(m.Ticket.id == id)
    if user.role != "admin":
        q = q.where(m.Ticket.user_id == user.id)
    ticket = db.scalar(q.with_for_update() if lock else q)
    if not ticket:
        raise AppError("NOT_FOUND", "工单不存在", 404)
    return ticket


@app.get(API + "/health/live")
def live():
    return {"status": "ok"}


@app.get(API + "/health/ready")
def ready(db=Depends(get_db)):
    try:
        db.scalar(select(m.KnowledgeState.id))
        Redis.from_url(settings().redis_url, socket_connect_timeout=2, socket_timeout=2).ping()
    except Exception:
        raise AppError("NOT_READY", "数据库、迁移或 Redis 尚未就绪", 503) from None
    return {"status": "ok", "model_mode": settings().model_mode}


@app.get(API + "/system")
def system():
    cfg = settings()
    return {
        "model_mode": cfg.model_mode,
        "retrieval_mode": cfg.retrieval_mode,
        "embedding_dimensions": 1024,
        "chat_model": cfg.llm_model if cfg.model_mode == "real" else "mock-snippet-v1",
        "embedding_model": cfg.embedding_model if cfg.model_mode == "real" else "mock-hash-v1",
        "index_key": cfg.index_key,
    }


@app.post(API + "/retrieval/compare")
async def compare_retrieval(body: RetrievalCompareInput, user=Depends(current_user), db=Depends(get_db)):
    """Compare ranking on one embedding under the caller's existing document permissions."""
    generation = db.get(m.KnowledgeState, 1).generation
    started = time.monotonic()
    model = provider()
    vector = (await model.embed([body.content]))[0]
    embedding_ms = round((time.monotonic() - started) * 1000, 3)
    modes = [body.first_mode, "hybrid" if body.first_mode == "vector" else "vector"]
    results, timings = {}, {}
    for mode in modes:
        started = time.monotonic()
        results[mode] = retrieve_with_vector(db, user, body.content, vector, mode=mode)
        timings[mode] = round((time.monotonic() - started) * 1000, 3)
    corpus = db.execute(
        allowed_query(user)
        .with_only_columns(m.Document.id, m.Document.name, m.DocumentVersion.id, maintain_column_froms=True)
        .distinct()
        .order_by(m.Document.id)
    ).all()
    # SQLAlchemy's identity map must not hide a concurrently changed generation.
    current_generation = db.scalar(select(m.KnowledgeState.generation).where(m.KnowledgeState.id == 1))
    if current_generation != generation:
        raise AppError("KNOWLEDGE_CHANGED", "知识库已变化，请重新进行对比", 409)
    return {
        "model_mode": settings().model_mode,
        "index_key": settings().index_key,
        "embedding_model": settings().embedding_model if settings().model_mode == "real" else "mock-hash-v1",
        "embedding_revision": settings().embedding_revision if settings().model_mode == "real" else "",
        "parameters": {
            "candidate_limit": 20,
            "rrf_k": 60,
            "top_k": settings().retrieval_top_k,
            "max_context_chars": settings().max_context_chars,
        },
        "generation": generation,
        "role": user.role,
        "order": modes,
        "embedding_ms": embedding_ms,
        "retrieval_ms": timings,
        "calls": model.calls,
        "corpus": [
            {"document_id": str(doc_id), "document_name": name, "version_id": str(version_id)}
            for doc_id, name, version_id in corpus
        ],
        "results": results,
    }


@app.post(API + "/auth/login")
def login(body: LoginInput, response: Response, request: Request, db=Depends(get_db)):
    login_limit(request, body.email)
    user = db.scalar(select(m.User).where(m.User.email == body.email.lower().strip()))
    try:
        # Equalize expensive password verification for unknown users.
        valid = passwords.verify(user.password_hash if user else DUMMY_HASH, body.password)
    except (VerifyMismatchError, VerificationError):
        valid = False
    if not user or not valid:
        raise AppError("LOGIN_FAILED", "账号或密码错误", 401)
    if body.entry_role and body.entry_role != user.role:
        target = "学生登录" if user.role == "student" else "管理端登录"
        raise AppError("LOGIN_ENTRY_MISMATCH", f"当前账号不适用于此入口，请切换至{target}", 403)
    token = secrets.token_urlsafe(32)
    make_session(db, user, token)
    db.commit()
    response.set_cookie(
        "campus_session",
        token,
        max_age=7 * 86400,
        httponly=True,
        secure=settings().cookie_secure,
        samesite="lax",
        path="/",
    )
    return user_data(user)


DUMMY_HASH = passwords.hash(secrets.token_urlsafe(32))


@app.post(API + "/auth/logout")
def logout(request: Request, response: Response, db=Depends(get_db)):
    login = db.scalar(
        select(m.LoginSession).where(
            m.LoginSession.token_hash == token_hash(request.cookies.get("campus_session", ""))
        )
    )
    if login:
        db.delete(login)
        db.commit()
    response.delete_cookie("campus_session", path="/")
    return {"ok": True}


@app.get(API + "/auth/me")
def me(user=Depends(current_user)):
    return user_data(user)


@app.get(API + "/documents")
def documents(page: Page = 1, page_size: Size = 20, user=Depends(admin), db=Depends(get_db)):
    return page_result(
        db,
        select(m.Document).where(m.Document.deleted.is_(False), m.Document.owner_id.is_(None)),
        page,
        page_size,
        lambda d: document_detail(db, d),
    )


async def add_version(db, doc, file):
    filename, key, digest = await storage.save(file)
    try:
        existing = db.scalar(
            select(m.DocumentVersion).where(
                m.DocumentVersion.document_id == doc.id,
                m.DocumentVersion.file_hash == digest,
                m.DocumentVersion.index_key == settings().index_key,
                m.DocumentVersion.chunk_policy == settings().chunk_policy_key,
            )
        )
        if existing:
            storage.remove(key)
            return db.scalar(select(m.ImportJob).where(m.ImportJob.version_id == existing.id))
        active = db.scalar(
            select(m.ImportJob)
            .join(m.DocumentVersion)
            .where(m.DocumentVersion.document_id == doc.id, m.ImportJob.status.in_(ACTIVE))
        )
        if active:
            raise AppError("IMPORT_IN_PROGRESS", "已有版本正在导入", 409)
        version = m.DocumentVersion(
            document_id=doc.id,
            filename=filename,
            storage_key=key,
            file_hash=digest,
            index_key=settings().index_key,
            chunk_policy=settings().chunk_policy_key,
        )
        db.add(version)
        db.flush()
        job = m.ImportJob(version_id=version.id)
        db.add(job)
        db.flush()
        return job
    except BaseException:
        storage.remove(key)
        raise


@app.post(API + "/documents", status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    visibility: Literal["public", "admin"] = Form("public"),
    user=Depends(admin),
    db=Depends(get_db),
):
    doc = m.Document(
        name=(file.filename or "资料").replace("\\", "/").split("/")[-1][:255], visibility=visibility
    )
    db.add(doc)
    db.flush()
    job = await add_version(db, doc, file)
    db.commit()
    enqueue(job.id)
    return {"document_id": str(doc.id), "job_id": str(job.id), "version_id": str(job.version_id)}


def find_document(db, id, lock=False):
    query = select(m.Document).where(
        m.Document.id == id, m.Document.deleted.is_(False), m.Document.owner_id.is_(None)
    )
    doc = db.scalar(query.with_for_update() if lock else query)
    if not doc:
        raise AppError("NOT_FOUND", "文档不存在", 404)
    return doc


@app.get(API + "/documents/{id}")
def get_document(id: uuid.UUID, user=Depends(admin), db=Depends(get_db)):
    doc = find_document(db, id)
    data = document_detail(db, doc)
    data["chunks"] = [
        dump(c, "content", "heading", "page", "paragraph")
        for c in db.scalars(
            select(m.Chunk)
            .where(m.Chunk.version_id == doc.active_version_id)
            .order_by(m.Chunk.ordinal)
            .limit(100)
        )
    ]
    return data


@app.post(API + "/documents/{id}/versions")
async def upload_version(
    id: uuid.UUID, file: UploadFile = File(...), user=Depends(admin), db=Depends(get_db)
):
    doc = find_document(db, id, True)
    job = await add_version(db, doc, file)
    db.commit()
    if job.status == "queued":
        enqueue(job.id)
    return {"document_id": str(doc.id), "job_id": str(job.id), "version_id": str(job.version_id)}


@app.post(API + "/documents/{id}/retry")
def retry(id: uuid.UUID, user=Depends(admin), db=Depends(get_db)):
    find_document(db, id, True)
    if db.scalar(
        select(m.ImportJob)
        .join(m.DocumentVersion)
        .where(m.DocumentVersion.document_id == id, m.ImportJob.status.in_(ACTIVE))
    ):
        raise AppError("IMPORT_IN_PROGRESS", "已有导入任务正在执行", 409)
    version = db.scalar(
        select(m.DocumentVersion)
        .where(m.DocumentVersion.document_id == id, m.DocumentVersion.index_key == settings().index_key)
        .order_by(m.DocumentVersion.created_at.desc())
        .limit(1)
    )
    if not version or version.status != "failed":
        raise AppError("NOT_RETRYABLE", "没有可重试的失败版本", 409)
    job = db.scalar(select(m.ImportJob).where(m.ImportJob.version_id == version.id).with_for_update())
    job.status = version.status = "queued"
    job.attempts, job.lease_token, job.error, version.error = 0, None, None, None
    db.commit()
    enqueue(job.id)
    return {"job_id": str(job.id)}


@app.patch(API + "/documents/{id}/visibility")
def visibility(id: uuid.UUID, body: VisibilityInput, user=Depends(admin), db=Depends(get_db)):
    doc = find_document(db, id, True)
    doc.visibility = body.visibility
    db.execute(
        update(m.KnowledgeState)
        .where(m.KnowledgeState.id == 1)
        .values(generation=m.KnowledgeState.generation + 1)
    )
    db.commit()
    return document_detail(db, doc)


@app.delete(API + "/documents/{id}")
def remove_document(id: uuid.UUID, user=Depends(admin), db=Depends(get_db)):
    doc = find_document(db, id, True)
    doc.deleted = True
    jobs = db.scalars(
        select(m.ImportJob)
        .join(m.DocumentVersion)
        .where(m.DocumentVersion.document_id == id, m.ImportJob.status.in_(ACTIVE))
        .with_for_update()
    ).all()
    for job in jobs:
        job.status, job.lease_token, job.error = "failed", None, "DOCUMENT_DELETED"
        db.get(m.DocumentVersion, job.version_id).status = "failed"
    db.execute(
        update(m.KnowledgeState)
        .where(m.KnowledgeState.id == 1)
        .values(generation=m.KnowledgeState.generation + 1)
    )
    db.commit()
    return {"ok": True}


@app.get(API + "/jobs/{id}")
def get_job(id: uuid.UUID, user=Depends(admin), db=Depends(get_db)):
    job = db.get(m.ImportJob, id)
    if not job:
        raise AppError("NOT_FOUND", "任务不存在", 404)
    version = db.get(m.DocumentVersion, job.version_id)
    doc = db.get(m.Document, version.document_id)
    if doc.owner_id and doc.owner_id != user.id:
        raise AppError("NOT_FOUND", "任务不存在", 404)
    return dump(job, "status", "attempts", "error", "started_at", "completed_at")


@app.get(API + "/sources/{id}")
def get_source(id: uuid.UUID, user=Depends(current_user), db=Depends(get_db)):
    chunk = db.get(m.Chunk, id)
    version = db.get(m.DocumentVersion, chunk.version_id) if chunk else None
    doc = db.get(m.Document, version.document_id) if version else None
    if not doc or doc.deleted or not document_access(doc, user) or version.status != "ready":
        raise AppError("NOT_FOUND", "来源不存在或已不可访问", 404)
    # Superseded published versions remain available only through already-authorized history citations.
    if doc.active_version_id != version.id and (user.role != "admin" or doc.owner_id):
        messages = db.scalars(
            select(m.Message).join(m.Conversation).where(m.Conversation.user_id == user.id)
        ).all()
        studies = (
            db.scalars(select(m.StudyRun).where(m.StudyRun.user_id == user.id)).all() if doc.owner_id else []
        )
        if not any(
            any(c.get("chunk_id") == str(id) for c in message.citations) for message in [*messages, *studies]
        ):
            raise AppError("NOT_FOUND", "历史来源不可访问", 404)
    return {
        **dump(chunk, "content", "heading", "page", "paragraph", "version_id", "source_spans"),
        "document_name": doc.name,
    }


@app.get(API + "/documents/{id}/download")
def download(id: uuid.UUID, user=Depends(admin), db=Depends(get_db)):
    doc = find_document(db, id)
    version = db.get(m.DocumentVersion, doc.active_version_id) if doc.active_version_id else None
    if not version:
        raise AppError("NOT_FOUND", "没有已发布文件", 404)
    return FileResponse(storage.path(version.storage_key), filename=version.filename)


@app.post(API + "/conversations", status_code=201)
def new_conversation(user=Depends(current_user), db=Depends(get_db)):
    conversation = m.Conversation(user_id=user.id)
    db.add(conversation)
    db.commit()
    return dump(conversation, "title", "mode")


@app.get(API + "/conversations")
def conversations(
    page: Page = 1,
    page_size: Size = 20,
    history: bool = False,
    user=Depends(current_user),
    db=Depends(get_db),
):
    query = select(m.Conversation).where(
        m.Conversation.user_id == user.id, m.Conversation.history_hidden.is_(False)
    )
    if not history:
        query = query.where(m.Conversation.recent_hidden.is_(False))
    return page_result(
        db,
        query,
        page,
        page_size,
        lambda c: dump(c, "title", "mode"),
    )


@app.delete(API + "/conversations")
def clear_conversations(history: bool = False, user=Depends(current_user), db=Depends(get_db)):
    query = select(m.Conversation).where(
        m.Conversation.user_id == user.id, m.Conversation.history_hidden.is_(False)
    )
    if not history:
        query = query.where(m.Conversation.recent_hidden.is_(False))
    conversations = list(db.scalars(query.order_by(m.Conversation.id).with_for_update()))
    ids = [c.id for c in conversations]
    if (
        history
        and ids
        and db.scalar(
            select(m.Message.id).where(m.Message.conversation_id.in_(ids), m.Message.status == "pending")
        )
    ):
        raise AppError("ANSWER_PENDING", "有回答正在生成，请稍后再清空历史记录", 409)
    for conversation in conversations:
        conversation.recent_hidden = True
        if history:
            # Keep references from submitted tickets intact while removing access to chat history.
            conversation.history_hidden = True
    db.commit()
    return {"cleared": len(conversations)}


def document_access(doc, user):
    return doc.owner_id == user.id if doc.owner_id else doc.visibility == "public" or user.role == "admin"


def safe_citations(db, citations, user):
    safe = []
    for citation in citations:
        doc = db.get(m.Document, uuid.UUID(citation["document_id"]))
        if doc and not doc.deleted and document_access(doc, user):
            safe.append(citation)
    return safe


@app.get(API + "/conversations/{id}")
def get_conversation(id: uuid.UUID, user=Depends(current_user), db=Depends(get_db)):
    c = conversation_owned(db, id, user)
    messages = []
    for message in db.scalars(
        select(m.Message).where(m.Message.conversation_id == id).order_by(m.Message.created_at, m.Message.id)
    ):
        data = dump(message, "role", "content", "status", "model_mode", "answerable", "answer_kind")
        data["citations"] = safe_citations(db, message.citations, user)
        if (
            message.role == "assistant"
            and message.citations
            and len(data["citations"]) != len(message.citations)
        ):
            data["content"] = "本回答引用的资料已撤回或权限已变更，请重新提问。"
            data["citations"], data["answerable"] = [], False
        messages.append(data)
    ticket = db.scalar(select(m.Ticket).join(m.TicketDraft).where(m.TicketDraft.conversation_id == id))
    return {**dump(c, "title", "mode"), "messages": messages, "ticket_id": str(ticket.id) if ticket else None}


def sse(event, data):
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


@app.post(API + "/conversations/{id}/messages")
def send_message(
    id: uuid.UUID, body: TextInput, request: Request, user=Depends(current_user), db=Depends(get_db)
):
    c = conversation_owned(db, id, user, True)
    if c.mode != "bot":
        raise AppError("TICKETED", "此会话已转为工单，请在工单中沟通", 409)
    if not body.content.strip():
        raise AppError("EMPTY_MESSAGE", "问题不能为空")
    if db.scalar(select(m.Message.id).where(m.Message.conversation_id == id, m.Message.status == "pending")):
        raise AppError("BUSY", "上一条问题正在处理", 409)
    c.title = body.content[:60]
    model = user_chat_provider(db, user.id, provider)
    chat_cfg = getattr(model, "chat_config", None) or settings()
    question_message = m.Message(
        conversation_id=id, role="user", content=body.content, model_mode=chat_cfg.model_mode
    )
    db.add(question_message)
    db.flush()
    answer = m.Message(
        conversation_id=id, role="assistant", content="", status="pending", model_mode=chat_cfg.model_mode
    )
    db.add(answer)
    db.commit()
    answer_id, question_id, user_id = answer.id, question_message.id, user.id
    request_id = request.state.request_id

    async def generate():
        started = time.monotonic()
        trace_status = "failed"

        def context(vector=None):
            with session() as work:
                current = work.get(m.User, user_id)
                sources = (
                    retrieve_with_vector(work, current, body.content, vector) if vector is not None else []
                )
                history = [
                    {"role": msg.role, "content": msg.content}
                    for msg in work.scalars(
                        select(m.Message)
                        .where(
                            m.Message.conversation_id == id,
                            m.Message.status == "complete",
                            m.Message.id != answer_id,
                            m.Message.id != question_id,
                        )
                        .order_by(m.Message.created_at.desc(), m.Message.id)
                        .limit(8)
                    ).all()
                    if not msg.citations
                    or len(safe_citations(work, msg.citations, current)) == len(msg.citations)
                ][::-1]
            return sources, history

        def persist(text, citations, valid, sources, answer_kind):
            with session() as work:
                # Recheck withdrawal/visibility after slow model calls, before storing/emitting any text.
                current = work.get(m.User, user_id)
                if len(safe_citations(work, sources, current)) != len(sources):
                    text, citations, valid = "资料权限或内容已变更，请重新提问。", [], False
                c = conversation_owned(work, id, current, True)
                msg = work.get(m.Message, answer_id)
                if c.mode != "bot" or msg.status != "pending":
                    raise AppError("CONVERSATION_CHANGED", "会话状态已变更，请刷新", 409)
                msg.content, msg.citations, msg.answerable, msg.status = (
                    text,
                    citations,
                    bool(valid),
                    "complete",
                )
                msg.answer_kind = answer_kind
                work.commit()
            return text, citations, valid

        def save_trace(trace_status):
            with session() as work:
                work.add(
                    m.RequestTrace(
                        request_id=request_id,
                        user_id=user_id,
                        model_mode=chat_cfg.model_mode,
                        model="mock" if chat_cfg.model_mode == "mock" else chat_cfg.llm_model,
                        duration_ms=int((time.monotonic() - started) * 1000),
                        calls=model.calls,
                        usage=model.usage,
                        status=trace_status,
                    )
                )
                work.commit()

        try:
            yield sse("status", {"phase": "routing", "message": "正在理解你的问题"})
            _, history = await asyncio.to_thread(context)
            answer_kind = forced_route(body.content, history) or await model.route(body.content, history)
            sources = []
            if answer_kind == "knowledge":
                yield sse("status", {"phase": "retrieving", "message": "正在查找校园 IT 资料"})
                embedding_model = provider() if getattr(model, "chat_config", None) else model
                vector = (await embedding_model.embed([body.content]))[0]
                sources, history = await asyncio.to_thread(context, vector)
            yield sse(
                "status",
                {
                    "phase": "generating",
                    "message": "正在整理回复" if answer_kind == "general" else "正在整理回答并校验来源",
                },
            )
            if await request.is_disconnected():
                raise asyncio.CancelledError()
            if answer_kind == "general":
                result = await model.general_answer(body.content, history)
                if result.sources or not result.answer.strip():
                    raise AppError("MODEL_OUTPUT", "普通回复格式不符合要求，请重试", 502)
            elif sources:
                result = await model.answer(body.content, sources, history)
            else:
                from app.schemas import Answer

                result = Answer(answer="知识库暂时没有可用资料，请创建工单。", answerable=False)
            numbers = {s["number"]: s for s in sources}
            valid = (
                result.answerable
                and bool(result.answer.strip())
                and (
                    answer_kind == "general"
                    or (bool(result.sources) and all(n in numbers for n in result.sources))
                )
            )
            citations = [numbers[n] for n in dict.fromkeys(result.sources)] if valid else []
            text = (
                result.answer
                if valid or answer_kind == "general"
                else "现有资料不足以支持可靠回答。请补充具体情况，或创建工单联系管理员。"
            )
            text, citations, valid = await asyncio.to_thread(
                persist, text, citations, valid, sources, answer_kind
            )
            trace_status = "complete"
            yield sse(
                "answer",
                {
                    "answer_id": str(answer_id),
                    "content": text,
                    "citations": citations,
                    "answerable": bool(valid),
                    "model_mode": chat_cfg.model_mode,
                    "answer_kind": answer_kind,
                },
            )
        except asyncio.CancelledError:
            trace_status = "interrupted"
            with session() as work:
                msg = work.get(m.Message, answer_id)
                if msg and msg.status == "pending":
                    msg.status, msg.content = "interrupted", "请求已中断，请重新提问"
                    work.commit()
            raise
        except Exception as exc:
            code = exc.code if isinstance(exc, AppError) else "ANSWER_FAILED"
            text = exc.message if isinstance(exc, AppError) else "回答失败，请稍后重试"
            with session() as work:
                msg = work.get(m.Message, answer_id)
                if msg and msg.status == "pending":
                    msg.status, msg.content = "failed", text
                    work.commit()
            yield sse("error", {"code": code, "message": text, "request_id": request_id})
        finally:
            await asyncio.to_thread(save_trace, trace_status)
        yield sse("done", {"answer_id": str(answer_id)})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


@app.post(API + "/conversations/{id}/ticket-draft")
async def draft_ticket(id: uuid.UUID, request: Request, user=Depends(current_user), db=Depends(get_db)):
    conversation_owned(db, id, user)
    history = get_conversation(id, user, db)["messages"]
    if not any(message["role"] == "user" for message in history):
        raise AppError("EMPTY_CONVERSATION", "请先描述问题")
    model, started, trace_status = user_chat_provider(db, user.id, provider), time.monotonic(), "failed"
    # Resolve the account configuration before releasing the read transaction.
    db.commit()
    try:
        summary = await model.draft([{"role": x["role"], "content": x["content"]} for x in history[-8:]])
        trace_status = "complete"
    finally:
        from app.tracing import record

        await asyncio.to_thread(
            record, request.state.request_id, user.id, "ticket_draft", model, started, trace_status
        )
    c = conversation_owned(db, id, user, True)
    if c.mode != "bot" or db.scalar(
        select(m.Message.id).where(m.Message.conversation_id == id, m.Message.status == "pending")
    ):
        raise AppError("CONVERSATION_CHANGED", "请等待回答完成或查看已有工单", 409)
    draft = db.scalar(select(m.TicketDraft).where(m.TicketDraft.conversation_id == id))
    if not draft:
        draft = m.TicketDraft(user_id=user.id, conversation_id=id, **summary.model_dump())
        db.add(draft)
    else:
        for name, value in summary.model_dump().items():
            setattr(draft, name, value)
    db.commit()
    return dump(draft, "title", "category", "description", "submitted")


def ticket_data(t):
    return dump(t, "title", "category", "description", "location", "status", "user_id")


@app.post(API + "/tickets", status_code=201)
def create_ticket(
    body: TicketInput,
    idempotency_key: Annotated[str, Header(min_length=1, max_length=120)],
    user=Depends(current_user),
    db=Depends(get_db),
):
    if not body.title.strip() or not body.description.strip():
        raise AppError("EMPTY_TICKET", "标题和描述不能为空")
    fingerprint = hashlib.sha256(body.model_dump_json().encode()).hexdigest()
    previous = db.scalar(
        select(m.Ticket).where(m.Ticket.user_id == user.id, m.Ticket.idempotency_key == idempotency_key)
    )
    if previous:
        if previous.request_hash != fingerprint:
            raise AppError("IDEMPOTENCY_CONFLICT", "同一提交标识不能用于不同内容", 409)
        return ticket_data(previous)
    draft = db.scalar(
        select(m.TicketDraft)
        .where(m.TicketDraft.id == body.draft_id, m.TicketDraft.user_id == user.id)
        .with_for_update()
    )
    if not draft:
        raise AppError("NOT_FOUND", "草稿不存在", 404)
    previous = db.scalar(select(m.Ticket).where(m.Ticket.draft_id == draft.id))
    if previous:
        if previous.request_hash != fingerprint:
            raise AppError("DRAFT_SUBMITTED", "该草稿已经提交", 409)
        return ticket_data(previous)
    c = conversation_owned(db, draft.conversation_id, user, True)
    if db.scalar(
        select(m.Message.id).where(m.Message.conversation_id == c.id, m.Message.status == "pending")
    ):
        raise AppError("BUSY", "请等待问答完成后提交", 409)
    sources = []
    for message in db.scalars(select(m.Message).where(m.Message.conversation_id == c.id)):
        sources.extend(safe_citations(db, message.citations, user))
    ticket = m.Ticket(
        user_id=user.id,
        **body.model_dump(exclude={"draft_id"}),
        draft_id=draft.id,
        idempotency_key=idempotency_key,
        request_hash=fingerprint,
        sources=sources,
    )
    db.add(ticket)
    draft.submitted, c.mode = True, "ticketed"
    try:
        db.flush()
        event = m.TicketEvent(ticket_id=ticket.id, user_id=user.id, before=None, after="open")
        db.add(event)
        db.flush()
        notify_ticket(db, ticket, user, event.id, "ticket_created", "收到新工单", ticket.title)
        db.commit()
    except IntegrityError:
        db.rollback()
        previous = db.scalar(
            select(m.Ticket).where(m.Ticket.user_id == user.id, m.Ticket.idempotency_key == idempotency_key)
        )
        if previous and previous.request_hash == fingerprint:
            return ticket_data(previous)
        raise AppError("IDEMPOTENCY_CONFLICT", "提交发生冲突，请刷新已有工单", 409) from None
    return ticket_data(ticket)


@app.get(API + "/tickets")
def tickets(
    page: Page = 1,
    page_size: Size = 20,
    status: str | None = None,
    user=Depends(current_user),
    db=Depends(get_db),
):
    query = select(m.Ticket)
    if user.role != "admin":
        query = query.where(m.Ticket.user_id == user.id)
    if status:
        query = query.where(m.Ticket.status == status)
    return page_result(db, query, page, page_size, ticket_data)


@app.get(API + "/tickets/{id}")
def get_ticket(id: uuid.UUID, user=Depends(current_user), db=Depends(get_db)):
    ticket = ticket_owned(db, id, user)
    replies = []
    for reply in db.scalars(
        select(m.TicketReply).where(m.TicketReply.ticket_id == id).order_by(m.TicketReply.created_at)
    ):
        author = db.get(m.User, reply.user_id)
        replies.append({**dump(reply, "content"), "author": author.name, "role": author.role})
    events = [
        dump(e, "before", "after")
        for e in db.scalars(
            select(m.TicketEvent).where(m.TicketEvent.ticket_id == id).order_by(m.TicketEvent.created_at)
        )
    ]
    sources = safe_citations(db, ticket.sources, user)
    return {**ticket_data(ticket), "replies": replies, "events": events, "sources": sources}


@app.post(API + "/tickets/{id}/replies", status_code=201)
def reply_ticket(id: uuid.UUID, body: TextInput, user=Depends(current_user), db=Depends(get_db)):
    ticket = ticket_owned(db, id, user, True)
    if ticket.status == "closed":
        raise AppError("TICKET_CLOSED", "工单已关闭", 409)
    if not body.content.strip():
        raise AppError("EMPTY_REPLY", "回复不能为空")
    reply = m.TicketReply(ticket_id=id, user_id=user.id, content=body.content)
    db.add(reply)
    db.flush()
    notify_ticket(
        db, ticket, user, reply.id, "ticket_reply", "工单收到新回复", ticket.title + "：" + body.content
    )
    db.commit()
    return dump(reply, "content")


@app.patch(API + "/tickets/{id}/status")
def change_status(id: uuid.UUID, body: StatusInput, user=Depends(current_user), db=Depends(get_db)):
    ticket = ticket_owned(db, id, user, True)
    allowed = (
        {
            "open": {"in_progress", "awaiting_student", "resolved"},
            "in_progress": {"awaiting_student", "resolved"},
            "awaiting_student": {"in_progress", "resolved"},
            "resolved": {"in_progress"},
        }
        if user.role == "admin"
        else {"resolved": {"open", "closed"}}
    )
    if body.status not in allowed.get(ticket.status, set()):
        raise AppError("INVALID_TRANSITION", "当前角色不能执行此状态变更", 409)
    event = m.TicketEvent(ticket_id=id, user_id=user.id, before=ticket.status, after=body.status)
    db.add(event)
    ticket.status = body.status
    db.flush()
    labels = {
        "open": "新建",
        "in_progress": "处理中",
        "awaiting_student": "待补充",
        "resolved": "已解决",
        "closed": "已关闭",
    }
    notify_ticket(
        db, ticket, user, event.id, "ticket_status", "工单状态更新", ticket.title + "：" + labels[body.status]
    )
    db.commit()
    return ticket_data(ticket)


def notification_data(item):
    return dump(
        item,
        "sequence",
        "ticket_id",
        "announcement_id",
        "todo_id",
        "study_job_id",
        "kind",
        "title",
        "content",
        "read_at",
    )


@app.get(API + "/notifications")
def notifications(page: Page = 1, page_size: Size = 20, user=Depends(current_user), db=Depends(get_db)):
    return page_result(
        db,
        select(m.Notification).where(m.Notification.user_id == user.id),
        page,
        page_size,
        notification_data,
    )


@app.get(API + "/notifications/updates")
def notification_updates(
    after: Annotated[int | None, Query(ge=0)] = None, user=Depends(current_user), db=Depends(get_db)
):
    query = select(m.Notification).where(m.Notification.user_id == user.id)
    rows = (
        db.scalars(
            query.where(m.Notification.sequence > after).order_by(m.Notification.sequence).limit(100)
        ).all()
        if after is not None
        else []
    )
    cursor = (
        rows[-1].sequence
        if rows
        else (
            after
            if after is not None
            else db.scalar(select(func.max(m.Notification.sequence)).where(m.Notification.user_id == user.id))
            or 0
        )
    )
    unread = db.scalar(
        select(func.count())
        .select_from(m.Notification)
        .where(m.Notification.user_id == user.id, m.Notification.read_at.is_(None))
    )
    return {"items": [notification_data(row) for row in rows], "cursor": cursor, "unread_count": unread}


@app.post(API + "/notifications/read-all")
def read_all_notifications(user=Depends(current_user), db=Depends(get_db)):
    db.execute(
        update(m.Notification)
        .where(m.Notification.user_id == user.id, m.Notification.read_at.is_(None))
        .values(read_at=m.now())
    )
    db.commit()
    return {"status": "ok"}


@app.post(API + "/notifications/{id}/read")
def read_notification(id: uuid.UUID, user=Depends(current_user), db=Depends(get_db)):
    item = db.scalar(
        select(m.Notification)
        .where(m.Notification.id == id, m.Notification.user_id == user.id)
        .with_for_update()
    )
    if not item:
        raise AppError("NOT_FOUND", "消息不存在", 404)
    if item.read_at is None:
        item.read_at = m.now()
    db.commit()
    return notification_data(item)


def register_campus_routes():
    from app.campus import router
    from app.study_jobs import router as study_router

    app.include_router(router)
    app.include_router(study_router)


register_campus_routes()
