import asyncio
import logging
import time
import uuid
from datetime import timedelta

from celery import Celery
from sqlalchemy import delete, select, update

from app.config import settings
from app.db import session
from app.errors import AppError
from app.models import Chunk, Document, DocumentVersion, ImportJob, KnowledgeState, Message, now
from app.parsing import chunk_sections, parse
from app.providers import provider
from app.storage import storage

logger = logging.getLogger(__name__)
celery = Celery("campus", broker=settings().redis_url)
celery.conf.update(
    imports=("app.course_materials", "app.study_jobs"),
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_serializer="json",
    accept_content=["json"],
    broker_connection_retry_on_startup=True,
    beat_schedule={
        "recover-imports": {"task": "app.jobs.recover", "schedule": 30.0},
        "todo-reminders": {"task": "app.jobs.reminders", "schedule": 30.0},
    },
)
ACTIVE = {"queued", "parsing", "chunking", "embedding"}


@celery.task(name="app.jobs.reminders")
def reminders():
    from app.campus_jobs import deliver_reminders

    return deliver_reminders()


def enqueue(job_id):
    try:
        import_document.delay(str(job_id))
    except Exception:
        # Database-backed outbox: scheduler will enqueue this queued task again.
        logger.warning("import_dispatch_deferred job=%s", job_id)


def owned_job(db, job_id, token):
    job = db.scalar(select(ImportJob).where(ImportJob.id == job_id).with_for_update())
    if not job or job.lease_token != token or job.status not in ACTIVE:
        raise AppError("JOB_LEASE_LOST", "任务已被重新调度", 409)
    return job


def set_phase(job_id, token, phase):
    with session() as db:
        job = owned_job(db, job_id, token)
        job.status, job.heartbeat = phase, now()
        db.get(DocumentVersion, job.version_id).status = phase
        db.commit()


async def process_import(job_id, prepared=None):
    job_id = uuid.UUID(str(job_id))
    token = str(uuid.uuid4())
    with session() as db:
        job = db.scalar(select(ImportJob).where(ImportJob.id == job_id).with_for_update())
        if not job or job.status != "queued":
            return
        version = db.get(DocumentVersion, job.version_id)
        doc = db.get(Document, version.document_id)
        if version.index_key != settings().index_key:
            job.status = version.status = "failed"
            job.error = version.error = "INDEX_MISMATCH: 模型配置已变化，请上传新版本重建索引"
            job.completed_at = now()
            db.commit()
            return
        if doc.deleted:
            job.status, version.status, job.error = "failed", "failed", "DOCUMENT_DELETED"
            db.commit()
            return
        job.status, version.status = "parsing", "parsing"
        job.lease_token, job.attempts = token, job.attempts + 1
        job.started_at = job.heartbeat = now()
        job.error = version.error = None
        db.execute(delete(Chunk).where(Chunk.version_id == version.id))
        filename, storage_key, version_id, document_id = (
            version.filename,
            version.storage_key,
            version.id,
            doc.id,
        )
        db.commit()
    model, started, trace_status = None, time.monotonic(), "failed"
    try:
        sections = (
            await asyncio.to_thread(parse, storage.path(storage_key), filename) if prepared is None else None
        )
        set_phase(job_id, token, "chunking")
        chunks = await asyncio.to_thread(chunk_sections, sections) if prepared is None else prepared[0]
        set_phase(job_id, token, "embedding")
        model = provider()
        for start in range(0, len(chunks), 16):
            group = chunks[start : start + 16]
            vectors = (
                await model.embed([c.heading + "\n" + c.content for c in group])
                if prepared is None
                else prepared[1][start : start + 16]
            )
            with session() as db:
                job = owned_job(db, job_id, token)
                job.heartbeat = now()
                for i, (c, vector) in enumerate(zip(group, vectors, strict=True), start):
                    db.add(
                        Chunk(
                            version_id=version_id,
                            ordinal=i,
                            content=c.content,
                            heading=c.heading,
                            page=c.page,
                            paragraph=c.paragraph,
                            source_spans=c.source_spans,
                            embedding=vector,
                        )
                    )
                db.commit()
        with session() as db:
            # Always lock the document before the job: the same order is used by deletion/retry APIs.
            doc = db.scalar(select(Document).where(Document.id == document_id).with_for_update())
            job = owned_job(db, job_id, token)
            version = db.get(DocumentVersion, version_id)
            if doc.deleted:
                raise AppError("DOCUMENT_DELETED", "文档已删除", 409)
            doc.active_version_id = version_id
            job.status = version.status = "ready"
            job.heartbeat = job.completed_at = now()
            job.lease_token = None
            db.execute(
                update(KnowledgeState)
                .where(KnowledgeState.id == 1)
                .values(generation=KnowledgeState.generation + 1)
            )
            db.commit()
        trace_status = "complete"
    except Exception as exc:
        code = f"{exc.code}: {exc.message}" if isinstance(exc, AppError) else "IMPORT_FAILED: 文档导入失败"
        with session() as db:
            job = db.scalar(select(ImportJob).where(ImportJob.id == job_id).with_for_update())
            if job and job.lease_token == token:
                job.status, job.error, job.completed_at, job.lease_token = "failed", code, now(), None
                version = db.get(DocumentVersion, job.version_id)
                version.status, version.error = "failed", code
                db.execute(delete(Chunk).where(Chunk.version_id == version.id))
                db.commit()
        logger.warning("import_failed job=%s code=%s", job_id, code.split(":")[0])
    finally:
        if model:
            from app.tracing import record

            record(job_id, None, "document_import", model, started, trace_status, embedding=True)


async def process_import_many(job_ids):
    """Share embedding calls across a small batch while retaining each file's lease/publication."""
    prepared, texts = [], []
    for id in job_ids:
        with session() as db:
            job = db.get(ImportJob, uuid.UUID(str(id)))
            if not job or job.status != "queued":
                continue
            version = db.get(DocumentVersion, job.version_id)
            doc = db.get(Document, version.document_id)
            if doc.deleted or version.index_key != settings().index_key:
                continue
            path, filename = storage.path(version.storage_key), version.filename
        try:
            chunks = await asyncio.to_thread(chunk_sections, await asyncio.to_thread(parse, path, filename))
            offset = len(texts)
            texts.extend(c.heading + "\n" + c.content for c in chunks)
            prepared.append((id, chunks, offset))
        except Exception:
            await process_import(id)
    if not texts:
        return
    model, started, vectors = provider(), time.monotonic(), []
    try:
        for offset in range(0, len(texts), 16):
            group = await model.embed(texts[offset : offset + 16])
            if len(group) != len(texts[offset : offset + 16]):
                raise AppError("EMBEDDING_OUTPUT", "嵌入数量不匹配", 502)
            vectors.extend(group)
        for id, chunks, offset in prepared:
            await process_import(id, (chunks, vectors[offset : offset + len(chunks)]))
    except Exception:
        # Each job keeps the normal retry/failure behavior when the shared request fails.
        for id, _, _ in prepared:
            await process_import(id)
    finally:
        from app.tracing import record

        record(
            str(job_ids[0]),
            None,
            "material_embedding",
            model,
            started,
            "complete" if vectors else "failed",
            embedding=True,
        )


@celery.task(name="app.jobs.import_document")
def import_document(job_id):
    asyncio.run(process_import(job_id))


@celery.task(name="app.jobs.recover")
def recover():
    from app.course_materials import recover_searches
    from app.study_jobs import recover_study_jobs

    recover_searches()
    recover_study_jobs()
    pending = []
    with session() as db:
        cutoff = now() - timedelta(seconds=settings().job_timeout_seconds)
        jobs = db.scalars(
            select(ImportJob).where(ImportJob.status.in_(ACTIVE)).with_for_update(skip_locked=True)
        ).all()
        for job in jobs:
            if job.status == "queued":
                pending.append(job.id)
            elif job.heartbeat < cutoff:
                version = db.get(DocumentVersion, job.version_id)
                job.lease_token = None
                if job.attempts < 3:
                    job.status = version.status = "queued"
                    pending.append(job.id)
                else:
                    job.status = version.status = "failed"
                    job.error = version.error = "WORKER_LOST: 后台任务多次超时，请重试"
        db.execute(
            update(Message)
            .where(Message.status == "pending", Message.created_at < cutoff)
            .values(status="interrupted", content="请求执行中断，请重新提问")
        )
        db.commit()
    for job_id in pending:
        enqueue(job_id)
