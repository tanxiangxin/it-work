"""Bounded, database-backed course material searches and normal document imports."""

import asyncio
import logging
import re
import time
import uuid
from datetime import timedelta
from io import BytesIO

from fastapi import UploadFile
from sqlalchemy import select

from app import models as m
from app.db import session
from app.errors import AppError
from app.jobs import celery
from app.providers import provider
from app.storage import storage
from app.tracing import record

logger = logging.getLogger(__name__)
SEARCH_ACTIVE = {"queued", "generating", "importing"}


def enqueue_search(id):
    try:
        generate_materials.delay(str(id))
    except Exception:
        logger.warning("material_search_dispatch_deferred job=%s", id)


def search_data(db, row):
    jobs = db.scalars(
        select(m.ImportJob).where(m.ImportJob.id.in_([uuid.UUID(id) for id in row.job_ids]))
    ).all()
    ready = sum(job.status == "ready" for job in jobs)
    failed = sum(job.status == "failed" for job in jobs)
    if row.generation_done and row.status == "importing" and ready + failed == len(row.job_ids):
        row.status = "complete" if not failed and not row.error else ("partial" if ready else "failed")
        if failed:
            row.error = (
                "部分资料导入失败，可在资料列表中重试。" if ready else "资料导入失败，请在资料列表中重试。"
            )
    return {
        "id": str(row.id),
        "status": row.status,
        "topic": row.topic,
        "limit": row.limit,
        "generated": len(row.document_ids),
        "ready": ready,
        "failed": failed,
        "error": row.error,
        "generation_done": row.generation_done,
        "timings": row.timings,
    }


def recover_searches():
    pending = []
    with session() as db:
        rows = db.scalars(
            select(m.MaterialSearch)
            .where(m.MaterialSearch.status.in_(SEARCH_ACTIVE))
            .with_for_update(skip_locked=True)
        ).all()
        for row in rows:
            if row.status == "queued":
                pending.append(row.id)
            elif row.status == "generating" and row.started_at < m.now() - timedelta(minutes=10):
                row.status, row.lease_token, row.error = (
                    "importing" if row.document_ids else "failed",
                    None,
                    "生成任务中断，已完成资料保留，可重新搜索。",
                )
                row.generation_done = True
            elif row.status == "importing":
                search_data(db, row)
        db.commit()
    for id in pending:
        enqueue_search(id)


@celery.task(name="app.course_materials.generate_materials")
def generate_materials(id):
    asyncio.run(process_search(id))


async def process_search(id):
    from app.jobs import enqueue, process_import_many

    id, token = uuid.UUID(str(id)), str(uuid.uuid4())
    with session() as db:
        row = db.scalar(select(m.MaterialSearch).where(m.MaterialSearch.id == id).with_for_update())
        if not row or row.status != "queued":
            return
        course = db.get(m.Course, row.course_id)
        existing_docs = db.scalars(
            select(m.Document)
            .where(
                m.Document.course_id == course.id,
                m.Document.owner_id == row.user_id,
                m.Document.deleted.is_(False),
                m.Document.archived.is_(False),
                m.Document.name.startswith("AI联网资料-"),
            )
            .order_by(m.Document.created_at.desc())
            .limit(50)
        ).all()
        existing = []
        for doc in existing_docs:
            headings = db.scalars(
                select(m.Chunk.heading).where(m.Chunk.version_id == doc.active_version_id).limit(12)
            ).all()
            existing.append(
                doc.name.removeprefix("AI联网资料-").removesuffix(".md")
                + "；已覆盖："
                + "、".join(dict.fromkeys(headings))[:500]
            )
        course_name, course_id, user_id, topic, limit = (
            course.name,
            course.id,
            row.user_id,
            row.topic,
            min(row.limit, 10),
        )
        row.status, row.lease_token, row.started_at = "generating", token, m.now()
        row.generation_done = False
        db.commit()
    model, started, status = provider(), time.monotonic(), "failed"
    created_keys, jobs = [], []
    committed = False
    embedding_ms, first_ready_ms = 0, None
    try:
        async for collection, sources in model.material_batches(course_name, topic, limit, existing):
            created_keys, jobs = [], []
            committed = False
            if (
                len(collection.materials) > 10
                or not sources
                or any(
                    not set(item.sources).issubset(range(1, len(sources) + 1))
                    for item in collection.materials
                )
            ):
                raise AppError("INVALID_CITATIONS", "生成资料或网页引用不符合要求，请重新搜索", 502)
            await persist_collection(
                id, token, course_id, user_id, limit, collection, sources, created_keys, jobs
            )
            committed = True
            if jobs:
                embedding_start = time.monotonic()
                await process_import_many(jobs)
                embedding_ms += int((time.monotonic() - embedding_start) * 1000)
                if first_ready_ms is None:
                    first_ready_ms = int((time.monotonic() - started) * 1000)
            for job in jobs:
                enqueue(job)
        with session() as db:
            row = db.scalar(select(m.MaterialSearch).where(m.MaterialSearch.id == id).with_for_update())
            if not row or row.lease_token != token:
                raise AppError("JOB_LEASE_LOST", "生成任务已中断", 409)
            if not row.document_ids:
                raise AppError("NO_NEW_MATERIALS", "没有足够依据生成完整主题资料，请调整主题后再次搜索", 422)
            row.status, row.lease_token, row.generation_done = "importing", None, True
            row.timings = {
                **getattr(model, "material_timings", {}),
                "embedding_and_publish_ms": embedding_ms,
                "first_batch_ready_ms": first_ready_ms,
                "total_ms": int((time.monotonic() - started) * 1000),
                "model_calls": model.calls,
            }
            search_data(db, row)
            db.commit()
        status = "complete"
    except Exception as error:
        if not committed:
            for key in created_keys:
                storage.remove(key)
        with session() as db:
            row = db.scalar(select(m.MaterialSearch).where(m.MaterialSearch.id == id).with_for_update())
            if row and row.lease_token == token:
                row.status, row.lease_token, row.generation_done = (
                    "importing" if row.document_ids else "failed",
                    None,
                    True,
                )
                row.error = error.message if isinstance(error, AppError) else "搜索生成失败，请稍后重试。"
                if row.document_ids:
                    search_data(db, row)
                db.commit()
        logger.warning(
            "material_search_failed job=%s code=%s",
            id,
            error.code if isinstance(error, AppError) else "INTERNAL",
        )
    finally:
        await asyncio.to_thread(record, id, user_id, "course_material_search", model, started, status)


async def persist_collection(id, token, course_id, user_id, limit, collection, sources, created_keys, jobs):
    from app.main import add_version

    with session() as db:
        # Course locks serialize repeated clicks and publication of the new batch.
        course = db.scalar(select(m.Course).where(m.Course.id == course_id).with_for_update())
        row = db.scalar(select(m.MaterialSearch).where(m.MaterialSearch.id == id).with_for_update())
        if not course or not row or row.status != "generating" or row.lease_token != token:
            raise AppError("JOB_LEASE_LOST", "生成任务已中断，请重新搜索", 409)
        names = set(
            db.scalars(
                select(m.Document.name).where(
                    m.Document.course_id == course_id,
                    m.Document.deleted.is_(False),
                    m.Document.archived.is_(False),
                )
            )
        )
        documents = []
        known_content = set()
        for existing_doc in db.scalars(
            select(m.Document).where(
                m.Document.course_id == course_id,
                m.Document.deleted.is_(False),
                m.Document.archived.is_(False),
            )
        ):
            version = (
                db.get(m.DocumentVersion, existing_doc.active_version_id)
                if existing_doc.active_version_id
                else None
            )
            if version and version.filename.lower().endswith(".md"):
                try:
                    original = storage.path(version.storage_key).read_text(encoding="utf-8-sig")
                    body = re.split(r"^##\s+网页来源\s*$", original, maxsplit=1, flags=re.M)[0]
                    body = re.sub(r"^# [^\n]*\n|^> AI 联网整理资料[^\n]*\n?", "", body, flags=re.M)
                    known_content.add("".join(body.split()))
                except (OSError, UnicodeError):
                    pass
        for item in collection.materials[: min(3, limit - len(row.document_ids))]:
            title = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", item.title).strip(". ")[:100]
            name = "AI联网资料-" + title + ".md"
            normalized = "".join(item.content.split())
            if not title or len(item.content.strip()) < 600 or name in names or normalized in known_content:
                continue
            known_content.add(normalized)
            names.add(name)
            references = "\n".join(
                f"- [{sources[n - 1].title}]({sources[n - 1].url})" for n in dict.fromkeys(item.sources)
            )
            content = f"# {title}\n\n> AI 联网整理资料，仅供学习参考，非原始课程讲义，请核对网页来源。\n\n{item.content}\n\n## 网页来源\n\n{references}\n"
            doc = m.Document(name=name, visibility="private", owner_id=user_id, course_id=course_id)
            db.add(doc)
            db.flush()
            file = UploadFile(filename=name, file=BytesIO(content.encode("utf-8")))
            try:
                job = await add_version(db, doc, file)
            finally:
                await file.close()
            created_keys.append(db.get(m.DocumentVersion, job.version_id).storage_key)
            jobs.append(job.id)
            documents.append(str(doc.id))
        row.document_ids = [*row.document_ids, *documents]
        row.job_ids = [*row.job_ids, *[str(job) for job in jobs]]
        row.started_at = m.now()
        db.commit()
