import asyncio
import time
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, File, Request, UploadFile
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError

from app import models as m
from app.campus_schemas import (
    CourseInput,
    MaterialSearchInput,
    NoticeCategory,
    NoticeExtractInput,
    NoticeInput,
    SavedInput,
    StudyInput,
    StudyOutput,
    SubscriptionsInput,
    TodoInput,
)
from app.config import settings
from app.course_materials import SEARCH_ACTIVE, enqueue_search, search_data
from app.db import get_db
from app.errors import AppError
from app.jobs import ACTIVE, enqueue
from app.main import Page, Size, add_version, document_detail, dump, page_result, safe_citations
from app.material_organization import organization_data, prepare_organization, switch_organization
from app.notifications import emit
from app.providers import insufficient_study_evidence, provider
from app.retrieval import allowed_query, retrieve_with_vector
from app.security import admin, current_user
from app.storage import storage
from app.tracing import record

router = APIRouter(prefix="/api/v1")


def owned(db, model, id, user, lock=False):
    query = select(model).where(model.id == id, model.user_id == user.id)
    row = db.scalar(query.with_for_update() if lock else query)
    if not row:
        raise AppError("NOT_FOUND", "资源不存在", 404)
    return row


def notice_access(db, id, user, lock=False):
    query = select(m.Announcement).where(m.Announcement.id == id)
    if user.role != "admin":
        query = query.where(m.Announcement.status == "published")
    row = db.scalar(query.with_for_update() if lock else query)
    if not row:
        raise AppError("NOT_FOUND", "通知不存在或已撤回", 404)
    return row


def notice_data(db, row, user):
    return {
        **dump(
            row,
            "title",
            "category",
            "content",
            "summary",
            "source_url",
            "audience",
            "location",
            "deadline",
            "status",
            "published_at",
        ),
        "saved": bool(
            db.scalar(
                select(m.SavedAnnouncement.id).where(
                    m.SavedAnnouncement.user_id == user.id, m.SavedAnnouncement.announcement_id == row.id
                )
            )
        ),
    }


@router.get("/subscriptions")
def subscriptions(user=Depends(current_user), db=Depends(get_db)):
    return {
        "categories": list(
            db.scalars(select(m.Subscription.category).where(m.Subscription.user_id == user.id))
        )
    }


@router.put("/subscriptions")
def set_subscriptions(body: SubscriptionsInput, user=Depends(current_user), db=Depends(get_db)):
    db.scalar(select(m.User).where(m.User.id == user.id).with_for_update())
    db.execute(delete(m.Subscription).where(m.Subscription.user_id == user.id))
    db.add_all(
        [m.Subscription(user_id=user.id, category=category) for category in sorted(set(body.categories))]
    )
    db.commit()
    return subscriptions(user, db)


@router.get("/announcements")
def list_notices(
    page: Page = 1,
    page_size: Size = 20,
    category: NoticeCategory | None = None,
    saved: bool = False,
    user=Depends(current_user),
    db=Depends(get_db),
):
    query = select(m.Announcement)
    if user.role != "admin":
        query = query.where(m.Announcement.status == "published")
    if category:
        query = query.where(m.Announcement.category == category)
    if saved:
        query = query.join(m.SavedAnnouncement).where(m.SavedAnnouncement.user_id == user.id)
    return page_result(db, query, page, page_size, lambda row: notice_data(db, row, user))


@router.get("/announcements/{id}")
def get_notice(id: uuid.UUID, user=Depends(current_user), db=Depends(get_db)):
    return notice_data(db, notice_access(db, id, user), user)


@router.post("/announcements/extract")
async def extract_notice(body: NoticeExtractInput, request: Request, user=Depends(admin)):
    model, started, status = provider(), time.monotonic(), "failed"
    try:
        result = await model.extract_notice(body.content)
        if result.deadline and (not result.deadline_evidence or result.deadline_evidence not in body.content):
            result.deadline, result.deadline_evidence = None, ""
        status = "complete"
        return {**result.model_dump(), "model_mode": settings().model_mode, "requires_review": True}
    finally:
        await asyncio.to_thread(
            record, request.state.request_id, user.id, "notice_extract", model, started, status
        )


@router.post("/announcements", status_code=201)
def create_notice(body: NoticeInput, user=Depends(admin), db=Depends(get_db)):
    row = m.Announcement(
        author_id=user.id, **body.model_dump(exclude={"source_url"}), source_url=str(body.source_url)
    )
    db.add(row)
    db.commit()
    return notice_data(db, row, user)


@router.put("/announcements/{id}")
def edit_notice(id: uuid.UUID, body: NoticeInput, user=Depends(admin), db=Depends(get_db)):
    row = notice_access(db, id, user, True)
    if row.status != "draft":
        raise AppError("NOTICE_PUBLISHED", "已发布通知不能直接修改，请撤回并创建修订通知", 409)
    for key, value in body.model_dump().items():
        setattr(row, key, str(value) if key == "source_url" else value)
    db.commit()
    return notice_data(db, row, user)


@router.post("/announcements/{id}/publish")
def publish_notice(id: uuid.UUID, user=Depends(admin), db=Depends(get_db)):
    row = notice_access(db, id, user, True)
    if row.status == "published":
        return notice_data(db, row, user)
    if row.status != "draft":
        raise AppError("NOTICE_WITHDRAWN", "撤回的通知不能再次发布，请创建修订通知", 409)
    row.status, row.published_at = "published", m.now()
    recipients = set(
        db.scalars(select(m.Subscription.user_id).where(m.Subscription.category == row.category))
    )
    recipients.discard(user.id)
    emit(db, recipients, row.id, "announcement", "订阅的校园通知已发布", row.title, announcement_id=row.id)
    db.commit()
    return notice_data(db, row, user)


@router.post("/announcements/{id}/withdraw")
def withdraw_notice(id: uuid.UUID, user=Depends(admin), db=Depends(get_db)):
    row = notice_access(db, id, user, True)
    row.status = "withdrawn"
    db.commit()
    return notice_data(db, row, user)


@router.put("/announcements/{id}/saved")
def save_notice(id: uuid.UUID, body: SavedInput, user=Depends(current_user), db=Depends(get_db)):
    notice_access(db, id, user)
    db.scalar(select(m.User).where(m.User.id == user.id).with_for_update())
    query = select(m.SavedAnnouncement).where(
        m.SavedAnnouncement.user_id == user.id, m.SavedAnnouncement.announcement_id == id
    )
    existing = db.scalar(query)
    if body.saved and not existing:
        db.add(m.SavedAnnouncement(user_id=user.id, announcement_id=id))
    elif not body.saved and existing:
        db.delete(existing)
    db.commit()
    return {"saved": body.saved}


def todo_data(db, row):
    notice = db.get(m.Announcement, row.announcement_id) if row.announcement_id else None
    return {
        **dump(row, "title", "notes", "announcement_id", "due_at", "remind_at", "completed", "reminded_at"),
        "source_status": notice.status if notice else None,
        "source_url": notice.source_url if notice else None,
    }


def validate_reminder(body, previous=None):
    if body.remind_at and (not previous or body.remind_at != previous.remind_at):
        if body.remind_at <= m.now():
            raise AppError("PAST_REMINDER", "提醒时间必须在未来")
        if previous and previous.reminded_at:
            raise AppError("REMINDER_DELIVERED", "此待办已经提醒过，请新建待办安排下一次提醒", 409)
    if body.remind_at and body.due_at and body.remind_at > body.due_at:
        raise AppError("INVALID_REMINDER", "提醒时间不能晚于截止时间")


@router.get("/todos")
def todos(
    page: Page = 1,
    page_size: Size = 20,
    completed: bool | None = None,
    user=Depends(current_user),
    db=Depends(get_db),
):
    query = select(m.Todo).where(m.Todo.user_id == user.id)
    if completed is not None:
        query = query.where(m.Todo.completed == completed)
    return page_result(db, query, page, page_size, lambda row: todo_data(db, row))


@router.post("/todos", status_code=201)
def create_todo(body: TodoInput, user=Depends(current_user), db=Depends(get_db)):
    if body.announcement_id:
        notice = notice_access(db, body.announcement_id, user)
        if notice.status != "published":
            raise AppError("NOTICE_NOT_PUBLISHED", "只能从已发布通知创建待办", 409)
        previous = db.scalar(
            select(m.Todo).where(m.Todo.user_id == user.id, m.Todo.announcement_id == body.announcement_id)
        )
        if previous:
            return todo_data(db, previous)
    validate_reminder(body)
    row = m.Todo(user_id=user.id, **body.model_dump())
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        previous = db.scalar(
            select(m.Todo).where(m.Todo.user_id == user.id, m.Todo.announcement_id == body.announcement_id)
        )
        if previous:
            return todo_data(db, previous)
        raise
    return todo_data(db, row)


@router.get("/todos/{id}")
def get_todo(id: uuid.UUID, user=Depends(current_user), db=Depends(get_db)):
    return todo_data(db, owned(db, m.Todo, id, user))


@router.put("/todos/{id}")
def update_todo(id: uuid.UUID, body: TodoInput, user=Depends(current_user), db=Depends(get_db)):
    row = owned(db, m.Todo, id, user, True)
    if body.announcement_id != row.announcement_id:
        raise AppError("SOURCE_IMMUTABLE", "不能修改待办关联的来源")
    validate_reminder(body, row)
    for key, value in body.model_dump().items():
        setattr(row, key, value)
    db.commit()
    return todo_data(db, row)


@router.delete("/todos/{id}")
def delete_todo(id: uuid.UUID, user=Depends(current_user), db=Depends(get_db)):
    row = owned(db, m.Todo, id, user, True)
    db.execute(delete(m.Notification).where(m.Notification.todo_id == id))
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.get("/courses")
def courses(page: Page = 1, page_size: Size = 20, user=Depends(current_user), db=Depends(get_db)):
    return page_result(
        db,
        select(m.Course).where(m.Course.user_id == user.id),
        page,
        page_size,
        lambda row: dump(row, "name"),
    )


@router.post("/courses", status_code=201)
def create_course(body: CourseInput, user=Depends(current_user), db=Depends(get_db)):
    row = m.Course(user_id=user.id, name=body.name)
    db.add(row)
    db.commit()
    return dump(row, "name")


def retire_course_document(db, doc):
    doc.deleted = True
    for job in db.scalars(
        select(m.ImportJob)
        .join(m.DocumentVersion)
        .where(m.DocumentVersion.document_id == doc.id, m.ImportJob.status.in_(ACTIVE))
        .with_for_update()
    ):
        job.status, job.lease_token, job.error = "failed", None, "DOCUMENT_DELETED"
        db.get(m.DocumentVersion, job.version_id).status = "failed"


@router.delete("/courses/{id}")
def delete_course(id: uuid.UUID, user=Depends(current_user), db=Depends(get_db)):
    course = owned(db, m.Course, id, user, True)
    # Serialize with material publication and retire imports before removing the course.
    for doc in db.scalars(
        select(m.Document).where(m.Document.course_id == id).order_by(m.Document.id).with_for_update()
    ):
        retire_course_document(db, doc)
        doc.course_id = None
    db.execute(delete(m.StudyRun).where(m.StudyRun.course_id == id))
    db.execute(delete(m.MaterialSearch).where(m.MaterialSearch.course_id == id))
    db.execute(delete(m.MaterialOrganization).where(m.MaterialOrganization.course_id == id))
    db.execute(
        update(m.KnowledgeState)
        .where(m.KnowledgeState.id == 1)
        .values(generation=m.KnowledgeState.generation + 1)
    )
    db.flush()
    db.delete(course)
    db.commit()
    return {"ok": True}


def generated_document_ids(db, course_id, user_id):
    # Provenance comes from completed search batches, not an editable file name.
    batches = db.scalars(
        select(m.MaterialSearch.document_ids).where(
            m.MaterialSearch.course_id == course_id, m.MaterialSearch.user_id == user_id
        )
    )
    organized = db.scalars(
        select(m.MaterialOrganization.new_document_ids).where(
            m.MaterialOrganization.course_id == course_id, m.MaterialOrganization.user_id == user_id
        )
    )
    return {uuid.UUID(id) for batch in [*batches, *organized] for id in batch}


def personal_document(db, course_id, id, user, lock=False):
    owned(db, m.Course, course_id, user, lock)
    query = select(m.Document).where(
        m.Document.id == id,
        m.Document.course_id == course_id,
        m.Document.owner_id == user.id,
        m.Document.deleted.is_(False),
    )
    doc = db.scalar(query.with_for_update() if lock else query)
    if not doc:
        raise AppError("NOT_FOUND", "资料不存在", 404)
    return doc


@router.get("/courses/{id}/documents")
def course_documents(
    id: uuid.UUID,
    page: Page = 1,
    page_size: Size = 20,
    source: Literal["uploaded", "ai"] | None = None,
    user=Depends(current_user),
    db=Depends(get_db),
):
    owned(db, m.Course, id, user)
    generated = generated_document_ids(db, id, user.id)
    query = select(m.Document).where(
        m.Document.course_id == id,
        m.Document.owner_id == user.id,
        m.Document.deleted.is_(False),
        m.Document.archived.is_(False),
    )
    if source:
        query = query.where(
            m.Document.id.in_(generated) if source == "ai" else m.Document.id.not_in(generated)
        )
    return page_result(
        db,
        query,
        page,
        page_size,
        lambda row: {**document_detail(db, row), "source": "ai" if row.id in generated else "uploaded"},
    )


@router.get("/courses/{course_id}/documents/{id}")
def course_document_detail(
    course_id: uuid.UUID,
    id: uuid.UUID,
    page: Page = 1,
    page_size: Size = 20,
    user=Depends(current_user),
    db=Depends(get_db),
):
    doc = personal_document(db, course_id, id, user)
    data = document_detail(db, doc)
    data["source"] = "ai" if id in generated_document_ids(db, course_id, user.id) else "uploaded"
    version = (
        db.get(m.DocumentVersion, doc.active_version_id)
        if doc.active_version_id
        else db.scalar(
            select(m.DocumentVersion)
            .where(m.DocumentVersion.document_id == doc.id)
            .order_by(m.DocumentVersion.created_at.desc())
            .limit(1)
        )
    )
    query = (
        select(m.Chunk).where(m.Chunk.version_id == version.id) if version else select(m.Chunk).where(False)
    )
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(query.order_by(m.Chunk.ordinal).offset((page - 1) * page_size).limit(page_size))
    data.update(
        chunks=[dump(row, "content", "heading", "page", "paragraph", "source_spans") for row in rows],
        chunk_total=total,
        preview="",
        preview_truncated=False,
        content_format="markdown" if version and version.filename.lower().endswith(".md") else "text",
    )
    # Text previews remain available while an uploaded/generated file is being indexed.
    if version and version.filename.lower().endswith((".md", ".txt")):
        try:
            with storage.path(version.storage_key).open(encoding="utf-8-sig") as file:
                text = file.read(30001)
            # Small Markdown files retain their original structure, without retrieval-chunk overlap.
            if not doc.active_version_id or (data["content_format"] == "markdown" and len(text) <= 30000):
                data.update(preview=text[:30000], preview_truncated=len(text) > 30000)
        except (OSError, UnicodeError):
            pass
    return data


@router.post("/courses/{id}/documents", status_code=201)
async def upload_course_document(
    id: uuid.UUID, file: UploadFile = File(...), user=Depends(current_user), db=Depends(get_db)
):
    owned(db, m.Course, id, user, True)
    doc = m.Document(
        name=(file.filename or "资料").replace("\\", "/").split("/")[-1][:255],
        visibility="private",
        owner_id=user.id,
        course_id=id,
    )
    db.add(doc)
    db.flush()
    job = await add_version(db, doc, file)
    db.commit()
    enqueue(job.id)
    return {"document_id": str(doc.id), "job_id": str(job.id)}


@router.get("/courses/{id}/material-search")
def material_search_status(id: uuid.UUID, user=Depends(current_user), db=Depends(get_db)):
    owned(db, m.Course, id, user)
    row = db.scalar(
        select(m.MaterialSearch)
        .where(m.MaterialSearch.course_id == id, m.MaterialSearch.user_id == user.id)
        .order_by(m.MaterialSearch.created_at.desc())
        .limit(1)
        .with_for_update()
    )
    result = search_data(db, row) if row else None
    db.commit()
    return {"job": result}


@router.get("/courses/{id}/material-organization")
def material_organization(id: uuid.UUID, user=Depends(current_user), db=Depends(get_db)):
    owned(db, m.Course, id, user)
    row = db.scalar(
        select(m.MaterialOrganization)
        .where(m.MaterialOrganization.course_id == id)
        .order_by(m.MaterialOrganization.created_at.desc())
        .limit(1)
    )
    return {"organization": organization_data(db, row) if row else None}


@router.post("/courses/{id}/material-organization", status_code=201)
async def organize_materials(id: uuid.UUID, user=Depends(current_user), db=Depends(get_db)):
    course = owned(db, m.Course, id, user, True)
    previous = db.scalar(
        select(m.MaterialOrganization).where(
            m.MaterialOrganization.course_id == id, m.MaterialOrganization.status == "draft"
        )
    )
    if previous:
        return organization_data(db, previous)
    searching = db.scalar(
        select(m.MaterialSearch.id)
        .where(m.MaterialSearch.course_id == id, m.MaterialSearch.status.in_(SEARCH_ACTIVE))
        .limit(1)
    )
    if searching:
        raise AppError("SEARCH_ACTIVE", "请等待本次资料生成完成后再整理", 409)
    row = await prepare_organization(db, course, user, generated_document_ids(db, id, user.id))
    return organization_data(db, row)


@router.post("/courses/{course_id}/material-organization/{id}/{action}")
def apply_material_organization(
    course_id: uuid.UUID,
    id: uuid.UUID,
    action: Literal["apply", "rollback"],
    user=Depends(current_user),
    db=Depends(get_db),
):
    owned(db, m.Course, course_id, user, True)
    row = owned(db, m.MaterialOrganization, id, user, True)
    if row.course_id != course_id:
        raise AppError("NOT_FOUND", "整理方案不存在", 404)
    return switch_organization(db, row, action == "apply")


@router.post("/courses/{id}/material-search", status_code=202)
def search_course_materials(
    id: uuid.UUID, body: MaterialSearchInput, user=Depends(current_user), db=Depends(get_db)
):
    owned(db, m.Course, id, user, True)
    for previous in db.scalars(
        select(m.MaterialSearch)
        .where(
            m.MaterialSearch.course_id == id,
            m.MaterialSearch.user_id == user.id,
            m.MaterialSearch.status.in_(SEARCH_ACTIVE),
        )
        .with_for_update()
    ).all():
        search_data(db, previous)
        if previous.status in SEARCH_ACTIVE:
            raise AppError("SEARCH_IN_PROGRESS", "课程资料正在生成或导入，请等待完成", 409)
    row = m.MaterialSearch(user_id=user.id, course_id=id, topic=body.topic.strip(), limit=body.limit)
    db.add(row)
    db.commit()
    result = search_data(db, row)
    enqueue_search(row.id)
    return result


@router.post("/courses/{course_id}/documents/{id}/versions")
async def update_course_document(
    course_id: uuid.UUID,
    id: uuid.UUID,
    file: UploadFile = File(...),
    user=Depends(current_user),
    db=Depends(get_db),
):
    doc = personal_document(db, course_id, id, user, True)
    job = await add_version(db, doc, file)
    db.commit()
    if job.status == "queued":
        enqueue(job.id)
    return {"document_id": str(doc.id), "job_id": str(job.id)}


@router.post("/courses/{course_id}/documents/{id}/retry")
def retry_course_document(
    course_id: uuid.UUID, id: uuid.UUID, user=Depends(current_user), db=Depends(get_db)
):
    personal_document(db, course_id, id, user, True)
    job = db.scalar(
        select(m.ImportJob)
        .join(m.DocumentVersion)
        .where(m.DocumentVersion.document_id == id)
        .order_by(m.ImportJob.created_at.desc())
        .limit(1)
        .with_for_update()
    )
    if not job or job.status != "failed":
        raise AppError("NOT_RETRYABLE", "没有可重试的失败任务", 409)
    version = db.get(m.DocumentVersion, job.version_id)
    if version.index_key != settings().index_key:
        raise AppError("INDEX_MISMATCH", "模型已变化，请重新上传资料", 409)
    job.status = version.status = "queued"
    job.attempts, job.lease_token, job.error, version.error = 0, None, None, None
    db.commit()
    enqueue(job.id)
    return {"job_id": str(job.id)}


@router.delete("/courses/{course_id}/documents/{id}")
def delete_course_document(
    course_id: uuid.UUID, id: uuid.UUID, user=Depends(current_user), db=Depends(get_db)
):
    doc = personal_document(db, course_id, id, user, True)
    retire_course_document(db, doc)
    db.execute(
        update(m.KnowledgeState)
        .where(m.KnowledgeState.id == 1)
        .values(generation=m.KnowledgeState.generation + 1)
    )
    db.commit()
    return {"ok": True}


def study_data(db, row, user):
    citations = safe_citations(db, row.citations, user)
    changed = len(citations) != len(row.citations)
    return {
        **dump(row, "kind", "question", "model_mode", "answer_kind"),
        "web_sources": row.web_sources,
        "content": "引用资料已删除，请重新生成。" if changed else row.content,
        "citations": [] if changed else citations,
        "exercises": [] if changed else row.exercises,
        "answerable": row.answerable and not changed,
    }


@router.get("/courses/{id}/study")
def study_history(
    id: uuid.UUID,
    page: Page = 1,
    page_size: Size = 20,
    kind: Literal["question", "outline", "practice"] | None = None,
    user=Depends(current_user),
    db=Depends(get_db),
):
    owned(db, m.Course, id, user)
    query = select(m.StudyRun).where(m.StudyRun.course_id == id, m.StudyRun.user_id == user.id)
    if kind is not None:
        query = query.where(m.StudyRun.kind == kind)
    return page_result(
        db,
        query,
        page,
        page_size,
        lambda row: study_data(db, row, user),
    )


@router.post("/courses/{id}/study", status_code=201)
async def study(
    id: uuid.UUID, body: StudyInput, request: Request, user=Depends(current_user), db=Depends(get_db)
):
    owned(db, m.Course, id, user)
    if body.kind == "question" and not body.content.strip():
        raise AppError("EMPTY_MESSAGE", "请填写问题")
    model, started, status = provider(), time.monotonic(), "failed"
    question = body.content.strip() or (
        "整理资料中的复习提纲" if body.kind == "outline" else "生成资料中的练习题"
    )
    history = []
    for previous in db.scalars(
        select(m.StudyRun)
        .where(m.StudyRun.course_id == id, m.StudyRun.user_id == user.id, m.StudyRun.kind == "question")
        .order_by(m.StudyRun.created_at.desc())
        .limit(4)
    ).all()[::-1]:
        if len(safe_citations(db, previous.citations, user)) == len(previous.citations):
            history.extend(
                [
                    {"role": "user", "content": previous.question},
                    {
                        "role": "assistant",
                        "content": (
                            "联网参考回答，未来自课程知识库："
                            if previous.answer_kind == "web"
                            else "课程资料回答："
                        )
                        + previous.content,
                    },
                ]
            )
    db.commit()
    try:
        if body.content.strip():
            vector = (await model.embed([question]))[0]
            sources = retrieve_with_vector(db, user, question, vector, course_id=id)
        else:
            # Round-robin documents so outlines do not only use the first uploaded file.
            rows = db.execute(
                allowed_query(user, id).order_by(m.Chunk.ordinal, m.Document.id).limit(100)
            ).all()
            sources, remaining = [], settings().max_context_chars
            for chunk, doc in rows:
                text = chunk.content[
                    : min(settings().chunk_size, remaining - len(chunk.heading[:512]) - len(doc.name))
                ]
                if not text or len(sources) >= 20:
                    break
                remaining -= len(text) + len(chunk.heading[:512]) + len(doc.name)
                sources.append(
                    {
                        "number": len(sources) + 1,
                        "chunk_id": str(chunk.id),
                        "version_id": str(chunk.version_id),
                        "document_id": str(doc.id),
                        "document_name": doc.name,
                        "content": text,
                        "heading": chunk.heading[:512],
                        "page": chunk.page,
                        "paragraph": chunk.paragraph,
                    }
                )
                if remaining <= 0:
                    break
        db.commit()
        if not sources:
            result = StudyOutput(answer="当前课程没有可用资料，请先上传并等待导入完成。", answerable=False)
        else:
            result = await model.study(body.kind, question, sources, history)
        numbers = {source["number"]: source for source in sources}
        all_numbers = set(result.sources) | {number for ex in result.exercises for number in ex.sources}
        if (result.answerable and (not result.sources or not all_numbers.issubset(numbers))) or (
            not result.answerable and (result.sources or result.exercises)
        ):
            raise AppError("INVALID_CITATIONS", "生成结果引用无效，请重试", 502)
        if body.kind != "practice" and result.exercises:
            raise AppError("MODEL_OUTPUT", "生成结果格式不符合任务要求", 502)
        if body.kind == "practice" and result.answerable and not result.exercises:
            raise AppError("MODEL_OUTPUT", "模型未返回练习题，请重试", 502)
        citations = [numbers[number] for number in sorted(all_numbers)] if result.answerable else []
        answer_kind, web_sources = "knowledge", []
        if body.kind == "question" and (
            not result.answerable
            or result.evidence_sufficient is False
            or insufficient_study_evidence(result.answer)
        ):
            # Search only the user's question; do not send private course snippets to search.
            web_result = await model.web_study(question)
            result = StudyOutput(answer=web_result.answer, answerable=True)
            answer_kind = "web"
            web_sources = [source.model_dump(mode="json") for source in web_result.sources]
            sources = []
            citations = []
        # A course may have been deleted while waiting for the model.
        owned(db, m.Course, id, user, True)
        # Recheck each document and published version after the model call.
        for source in sorted(sources, key=lambda item: item["document_id"]):
            doc = db.scalar(
                select(m.Document)
                .where(m.Document.id == uuid.UUID(source["document_id"]))
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if (
                not doc
                or doc.deleted
                or doc.archived
                or doc.owner_id != user.id
                or doc.course_id != id
                or str(doc.active_version_id) != source["version_id"]
            ):
                raise AppError("MATERIAL_CHANGED", "资料已删除或更新，请重新生成", 409)
        row = m.StudyRun(
            user_id=user.id,
            course_id=id,
            kind=body.kind,
            question=question,
            content=result.answer,
            citations=citations,
            exercises=[ex.model_dump() for ex in result.exercises],
            answerable=result.answerable,
            model_mode=settings().model_mode,
            answer_kind=answer_kind,
            web_sources=web_sources,
        )
        db.add(row)
        db.commit()
        status = "complete"
        return study_data(db, row, user)
    finally:
        await asyncio.to_thread(
            record, request.state.request_id, user.id, "study_" + body.kind, model, started, status
        )
