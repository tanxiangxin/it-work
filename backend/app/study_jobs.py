"""Persisted learning tasks. Result publication and completion are one transaction."""

import asyncio
import logging
import uuid
from datetime import timedelta
from importlib import import_module
from types import SimpleNamespace

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app import models as m
from app.campus_schemas import PracticeSubmission, StudyInput
from app.db import get_db, session
from app.errors import AppError
from app.jobs import celery
from app.notifications import emit
from app.security import current_user

router = APIRouter(prefix="/api/v1")
logger = logging.getLogger(__name__)
ACTIVE = {"queued", "running"}
LABELS = {"question": "资料问答", "outline": "复习提纲", "practice": "练习题", "grade": "练习评分"}


def enqueue_study(id):
    try:
        run_study_job.delay(str(id))
    except Exception:
        logger.warning("study_dispatch_deferred job=%s", id)


def job_data(db, job, user, result=False):
    from app.campus import study_data

    return {
        "id": str(job.id),
        "course_id": str(job.course_id),
        "kind": job.kind,
        "status": job.status,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "completed_at": job.completed_at,
        "error": job.error,
        "title": job.payload.get("content") or LABELS[job.kind],
        "run_id": str(job.run_id) if job.run_id else None,
        "result": study_data(db, db.get(m.StudyRun, job.run_id), user)
        if result and job.status == "complete" and job.run_id
        else None,
    }


def create_job(db, course_id, user, kind, payload, run_id=None):
    from app.campus import owned

    owned(db, m.Course, course_id, user, lock=True)
    if db.scalar(
        select(m.StudyJob.id).where(m.StudyJob.course_id == course_id, m.StudyJob.status.in_(ACTIVE))
    ):
        raise AppError("STUDY_BUSY", "本课程已有学习任务在处理，请完成后再提交", 409)
    job = m.StudyJob(user_id=user.id, course_id=course_id, kind=kind, payload=payload, run_id=run_id)
    db.add(job)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AppError("STUDY_BUSY", "本课程已有学习任务在处理", 409) from None
    enqueue_study(job.id)
    return job_data(db, job, user)


@router.post("/courses/{id}/study-jobs", status_code=202)
def create_study_job(id: uuid.UUID, body: StudyInput, user=Depends(current_user), db=Depends(get_db)):
    if body.kind == "question" and not body.content.strip():
        raise AppError("EMPTY_MESSAGE", "请填写问题")
    return create_job(db, id, user, body.kind, body.model_dump())


@router.post("/courses/{id}/study/{run_id}/grade-jobs", status_code=202)
def create_grade_job(
    id: uuid.UUID, run_id: uuid.UUID, body: PracticeSubmission, user=Depends(current_user), db=Depends(get_db)
):
    from app.campus import owned, study_data

    owned(db, m.Course, id, user, lock=True)
    run = owned(db, m.StudyRun, run_id, user)
    if run.course_id != id:
        raise AppError("NOT_FOUND", "资源不存在", 404)
    data = study_data(db, run, user)
    if run.kind != "practice" or not data["exercises"] or not data["answerable"]:
        raise AppError("PRACTICE_UNAVAILABLE", "练习不可用或引用资料已删除", 409)
    if len(body.answers) != len(run.exercises):
        raise AppError("INCOMPLETE_ANSWERS", "请完成每一道题后再提交")
    return create_job(db, id, user, "grade", body.model_dump(), run_id)


@router.get("/courses/{id}/study-jobs")
def list_study_jobs(id: uuid.UUID, user=Depends(current_user), db=Depends(get_db)):
    from app.campus import owned

    owned(db, m.Course, id, user)
    jobs = db.scalars(
        select(m.StudyJob)
        .where(m.StudyJob.course_id == id, m.StudyJob.user_id == user.id)
        .order_by(m.StudyJob.created_at.desc(), m.StudyJob.id)
        .limit(20)
    ).all()
    # Include an active task even when newer failed history has accumulated.
    active = db.scalar(select(m.StudyJob).where(m.StudyJob.course_id == id, m.StudyJob.status.in_(ACTIVE)))
    if active and all(job.id != active.id for job in jobs):
        jobs.insert(0, active)
    return {"items": [job_data(db, job, user) for job in jobs]}


@router.get("/study-jobs/{id}")
def get_study_job(id: uuid.UUID, user=Depends(current_user), db=Depends(get_db)):
    from app.campus import owned

    job = owned(db, m.StudyJob, id, user)
    return job_data(db, job, user, result=True)


@router.post("/study-jobs/{id}/retry", status_code=202)
def retry_study_job(id: uuid.UUID, user=Depends(current_user), db=Depends(get_db)):
    from app.campus import owned

    job = owned(db, m.StudyJob, id, user)
    if job.status != "failed":
        raise AppError("RETRY_UNAVAILABLE", "仅失败任务可以重试", 409)
    # A new task has its own event ID, so completion notifications stay idempotent.
    return create_job(db, job.course_id, user, job.kind, job.payload, job.run_id)


def finish_job(db, background, run_id):
    id, token = background
    job = db.scalar(
        select(m.StudyJob)
        .where(m.StudyJob.id == id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not job or job.status != "running" or job.lease_token != token:
        raise AppError("JOB_LEASE_LOST", "任务已中断，请重试", 409)
    job.status, job.run_id, job.completed_at, job.lease_token = "complete", run_id, m.now(), None
    emit(
        db,
        {job.user_id},
        job.id,
        "study_complete",
        LABELS[job.kind] + "已完成",
        "点击查看学习结果。",
        study_job_id=job.id,
    )


def fail_job(db, job, error):
    job.status, job.error, job.lease_token, job.completed_at = "failed", error, None, m.now()
    emit(db, {job.user_id}, job.id, "study_failed", LABELS[job.kind] + "未完成", error, study_job_id=job.id)


@celery.task(name="app.study_jobs.run")
def run_study_job(id):
    asyncio.run(process_study_job(id))


async def process_study_job(id):
    # Campus reuses helpers from main. Initialize them first in a fresh Celery process.
    import_module("app.main")
    from app.campus import execute_practice, execute_study

    id, token = uuid.UUID(str(id)), str(uuid.uuid4())
    with session() as db:
        job = db.scalar(select(m.StudyJob).where(m.StudyJob.id == id).with_for_update())
        if not job or job.status != "queued":
            return
        job.status, job.lease_token, job.started_at = "running", token, m.now()
        course_id, kind, payload, run_id, user_id = (
            job.course_id,
            job.kind,
            job.payload,
            job.run_id,
            job.user_id,
        )
        db.commit()
    try:
        with session() as db:
            user = db.get(m.User, user_id)
            request = SimpleNamespace(state=SimpleNamespace(request_id=str(id)))
            if kind == "grade":
                await execute_practice(
                    course_id,
                    run_id,
                    PracticeSubmission.model_validate(payload),
                    request,
                    user,
                    db,
                    (id, token),
                )
            else:
                await execute_study(
                    course_id, StudyInput.model_validate(payload), request, user, db, (id, token)
                )
    except Exception as error:
        logger.warning("study_job_failed job=%s code=%s", id, getattr(error, "code", type(error).__name__))
        with session() as db:
            job = db.scalar(select(m.StudyJob).where(m.StudyJob.id == id).with_for_update())
            if job and job.status == "running" and job.lease_token == token:
                fail_job(db, job, error.message if isinstance(error, AppError) else "学习任务失败，请重试。")
                db.commit()


def recover_study_jobs():
    pending = []
    with session() as db:
        jobs = db.scalars(
            select(m.StudyJob).where(m.StudyJob.status.in_(ACTIVE)).with_for_update(skip_locked=True)
        ).all()
        for job in jobs:
            if job.status == "queued":
                pending.append(job.id)
            elif job.started_at < m.now() - timedelta(minutes=30):
                fail_job(db, job, "学习任务中断或超时，请重试。")
        db.commit()
    for id in pending:
        enqueue_study(id)
