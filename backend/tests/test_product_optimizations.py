import asyncio
import subprocess
import sys
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app import models as m
from app.campus_schemas import StudyOutput
from app.db import session
from app.errors import AppError
from app.providers import MockProvider
from app.study_jobs import process_study_job, recover_study_jobs
from tests.test_campus_features import API, course, notice, upload


def test_fresh_worker_process_initializes_learning_routes(database):
    code = f"from app.study_jobs import process_study_job; import asyncio; asyncio.run(process_study_job('{uuid.uuid4()}'))"
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_notice_search_dates_and_visibility(clients):
    student, admin, other = clients
    a = notice(admin, title="奖学金报名通知")
    b = notice(admin, title="校园网络维护")
    notice(admin, title="奖学金草稿")
    for row in (a, b):
        admin.post(f"{API}/announcements/{row['id']}/publish")
    with session() as db:
        db.get(m.Announcement, uuid.UUID(a["id"])).published_at = datetime(
            2030, 1, 2, 23, 59, tzinfo=ZoneInfo("Asia/Shanghai")
        )
        db.get(m.Announcement, uuid.UUID(b["id"])).published_at = datetime(
            2030, 1, 3, 0, 0, tzinfo=ZoneInfo("Asia/Shanghai")
        )
        db.commit()
    result = student.get(
        API + "/announcements",
        params={"q": "奖学金", "published_from": "2030-01-02", "published_to": "2030-01-02"},
    ).json()
    assert [row["id"] for row in result["items"]] == [a["id"]]
    assert student.get(API + "/announcements?q=%").json()["total"] == 0
    assert (
        student.get(API + "/announcements?published_from=2030-01-03&published_to=2030-01-02").status_code
        == 422
    )
    student.put(f"{API}/announcements/{a['id']}/saved", json={"saved": True})
    assert student.get(API + "/announcements?saved=true&q=奖学金").json()["total"] == 1
    assert other.get(API + "/announcements?saved=true&q=奖学金").json()["total"] == 0
    # The largest valid date must not overflow when calculating an exclusive next day.
    response = student.get(API + "/announcements?published_to=9999-12-31")
    assert response.status_code == 200 and response.json()["total"] == 2


def test_todo_search_due_filters_and_order(clients):
    student, _, other = clients
    now = m.now()
    today = now.astimezone(ZoneInfo("Asia/Shanghai")).replace(hour=12, minute=0, second=0, microsecond=0)
    ids = {}
    for title, due, completed in [
        ("报名临近", now + timedelta(hours=1), False),
        ("报名稍后", now + timedelta(days=2), False),
        ("报名逾期", now - timedelta(days=2), False),
        ("报名已办", now + timedelta(hours=2), True),
        ("报名今天", today, False),
        ("报名无期限", None, False),
    ]:
        ids[title] = student.post(
            API + "/todos",
            json={"title": title, "due_at": due.isoformat() if due else None, "completed": completed},
        ).json()["id"]
    assert [row["id"] for row in student.get(API + "/todos?q=稍后").json()["items"]] == [ids["报名稍后"]]
    assert student.get(API + "/todos?due=overdue").json()["items"][0]["completed"] is False
    assert ids["报名逾期"] in {row["id"] for row in student.get(API + "/todos?due=overdue").json()["items"]}
    assert ids["报名今天"] in {row["id"] for row in student.get(API + "/todos?due=today").json()["items"]}
    upcoming = student.get(API + "/todos?due=upcoming").json()["items"]
    assert [row["id"] for row in upcoming if row["title"] != "报名今天"] == [ids["报名临近"], ids["报名稍后"]]
    assert all(not row["completed"] for row in upcoming)
    assert other.get(API + "/todos?q=报名&due=upcoming").json()["total"] == 0
    assert student.get(API + "/todos?due=invalid").status_code == 422
    rows = student.get(API + "/todos").json()["items"]
    assert rows[-1]["id"] == ids["报名已办"]


def test_background_generation_grading_and_notifications(clients):
    student, admin, other = clients
    id = course(student)
    upload(student, id)
    created = student.post(f"{API}/courses/{id}/study-jobs", json={"kind": "practice"})
    assert created.status_code == 202
    job_id = created.json()["id"]
    assert student.post(f"{API}/courses/{id}/study-jobs", json={"kind": "outline"}).status_code == 409
    assert other.get(f"{API}/study-jobs/{job_id}").status_code == 404
    assert admin.get(f"{API}/study-jobs/{job_id}").status_code == 404
    asyncio.run(process_study_job(job_id))
    asyncio.run(process_study_job(job_id))
    job = student.get(f"{API}/study-jobs/{job_id}").json()
    assert job["status"] == "complete"
    assert len(job["result"]["exercises"]) == 10
    run = job["result"]
    assert student.get(f"{API}/courses/{id}/study").json()["total"] == 1
    messages = student.get(API + "/notifications").json()["items"]
    assert len(messages) == 1 and messages[0]["study_job_id"] == job_id
    assert other.get(API + "/notifications").json()["total"] == 0
    answers = [exercise["answer"] for exercise in run["exercises"]]
    response = student.post(f"{API}/courses/{id}/study/{run['id']}/grade-jobs", json={"answers": answers})
    assert response.status_code == 202
    grade_id = response.json()["id"]
    asyncio.run(process_study_job(grade_id))
    grade = student.get(f"{API}/study-jobs/{grade_id}").json()
    assert grade["status"] == "complete"
    assert grade["result"]["grading"]["total_score"] == 100
    assert student.post(f"{API}/study-jobs/{grade_id}/retry").status_code == 409


def test_background_failure_retry_and_recovery(clients, monkeypatch):
    student, _, other = clients
    id = course(student)
    upload(student, id)
    original = MockProvider.study

    async def fail(*args):
        raise AppError("MODEL_DOWN", "模型暂时不可用", 503)

    monkeypatch.setattr(MockProvider, "study", fail)
    job_id = student.post(f"{API}/courses/{id}/study-jobs", json={"kind": "outline"}).json()["id"]
    asyncio.run(process_study_job(job_id))
    assert student.get(f"{API}/study-jobs/{job_id}").json()["error"] == "模型暂时不可用"
    assert student.get(f"{API}/courses/{id}/study").json()["total"] == 0
    assert other.post(f"{API}/study-jobs/{job_id}/retry").status_code == 404
    monkeypatch.setattr(MockProvider, "study", original)
    new_job = student.post(f"{API}/study-jobs/{job_id}/retry").json()
    assert new_job["id"] != job_id
    dispatched = []
    monkeypatch.setattr("app.study_jobs.enqueue_study", dispatched.append)
    recover_study_jobs()
    assert uuid.UUID(new_job["id"]) in dispatched
    with session() as db:
        row = db.get(m.StudyJob, uuid.UUID(new_job["id"]))
        row.status, row.started_at, row.lease_token = (
            "running",
            m.now() - timedelta(minutes=31),
            "lost-worker",
        )
        db.commit()
    recover_study_jobs()
    assert student.get(f"{API}/study-jobs/{new_job['id']}").json()["status"] == "failed"
    retried = student.post(f"{API}/study-jobs/{new_job['id']}/retry").json()
    asyncio.run(process_study_job(retried["id"]))
    assert student.get(f"{API}/study-jobs/{retried['id']}").json()["status"] == "complete"


def test_deleted_course_cancels_background_job(clients):
    student, _, _ = clients
    id = course(student)
    job_id = student.post(f"{API}/courses/{id}/study-jobs", json={"kind": "outline"}).json()["id"]
    assert student.delete(f"{API}/courses/{id}").status_code == 200
    asyncio.run(process_study_job(job_id))
    assert student.get(f"{API}/study-jobs/{job_id}").status_code == 404


def test_lost_job_lease_does_not_publish_result(clients, monkeypatch):
    student, _, _ = clients
    id = course(student)
    upload(student, id)
    job_id = student.post(f"{API}/courses/{id}/study-jobs", json={"kind": "outline"}).json()["id"]

    async def lose_lease(self, kind, question, sources, history):
        with session() as db:
            job = db.get(m.StudyJob, uuid.UUID(job_id))
            job.status, job.lease_token = "failed", None
            db.commit()
        return StudyOutput(answer="提纲", answerable=True, sources=[sources[0]["number"]])

    monkeypatch.setattr(MockProvider, "study", lose_lease)
    asyncio.run(process_study_job(job_id))
    assert student.get(f"{API}/courses/{id}/study").json()["total"] == 0
    with session() as db:
        assert not db.scalar(select(m.Notification).where(m.Notification.study_job_id == uuid.UUID(job_id)))
