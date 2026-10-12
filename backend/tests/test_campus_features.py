import asyncio
import uuid
from datetime import timedelta

from sqlalchemy import select

from app import models as m
from app.campus_jobs import deliver_reminders
from app.campus_schemas import NoticeExtraction, StudyOutput
from app.db import session
from app.jobs import process_import
from app.providers import MockProvider
from app.retrieval import allowed_query

API = "/api/v1"


def notice(admin, **changes):
    body = {
        "title": "官方通知测试",
        "category": "教学",
        "content": "请阅读官方通知，报名截止时间未明确。",
        "source_url": "https://jwc.hut.edu.cn/",
        "summary": "测试摘要",
        **changes,
    }
    response = admin.post(API + "/announcements", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def course(student, name="数据库原理"):
    response = student.post(API + "/courses", json={"name": name})
    assert response.status_code == 201
    return response.json()["id"]


def upload(
    student, course_id, content="# 事务\n\n数据库事务具有原子性、一致性、隔离性和持久性。", document_id=None
):
    path = f"/courses/{course_id}/documents" + (f"/{document_id}/versions" if document_id else "")
    response = student.post(API + path, files={"file": ("notes.md", content.encode())})
    assert response.status_code in {200, 201}, response.text
    data = response.json()
    asyncio.run(process_import(data["job_id"]))
    return data


def test_notice_review_publish_subscription_and_saved(clients):
    student, admin, other = clients
    assert student.post(API + "/announcements", json={}).status_code in {403, 422}
    student.put(API + "/subscriptions", json={"categories": ["教学", "教学"]})
    assert student.get(API + "/subscriptions").json()["categories"] == ["教学"]
    row = notice(admin)
    assert student.get(API + "/announcements").json()["total"] == 0
    assert student.get(API + "/announcements/" + row["id"]).status_code == 404
    assert student.post(API + f"/announcements/{row['id']}/publish").status_code == 403
    admin.post(API + f"/announcements/{row['id']}/publish")
    admin.post(API + f"/announcements/{row['id']}/publish")
    assert student.get(API + "/notifications").json()["total"] == 1
    assert other.get(API + "/notifications").json()["total"] == 0
    assert student.get(API + "/announcements/" + row["id"]).json()["deadline"] is None
    for _ in range(2):
        assert student.put(API + f"/announcements/{row['id']}/saved", json={"saved": True}).status_code == 200
    assert student.get(API + "/announcements?saved=true").json()["total"] == 1
    assert other.get(API + "/announcements?saved=true").json()["total"] == 0
    payload = {"title": row["title"], "announcement_id": row["id"]}
    a = student.post(API + "/todos", json=payload).json()
    b = student.post(API + "/todos", json=payload).json()
    assert a["id"] == b["id"]
    admin.post(API + f"/announcements/{row['id']}/withdraw")
    assert student.get(API + "/announcements/" + row["id"]).status_code == 404
    assert student.get(API + "/todos/" + a["id"]).json()["source_status"] == "withdrawn"
    assert admin.post(API + f"/announcements/{row['id']}/publish").status_code == 409


def test_notice_validation_and_extraction_review(clients, monkeypatch):
    student, admin, _ = clients
    payload = {"title": "a", "category": "教学", "content": "a", "source_url": "https://hut.edu.cn.evil.test"}
    assert admin.post(API + "/announcements", json=payload).status_code == 422
    payload["source_url"] = "https://hut.edu.cn"
    payload["deadline"] = "2026-12-01T12:00:00"
    assert admin.post(API + "/announcements", json=payload).status_code == 422
    assert student.post(API + "/announcements/extract", json={"content": "a"}).status_code == 403
    result = admin.post(API + "/announcements/extract", json={"content": "通知\n截止时间未明确"}).json()
    assert result["deadline"] is None and result["requires_review"] and result["model_mode"] == "mock"

    class Fabricated(MockProvider):
        async def extract_notice(self, content):
            return NoticeExtraction(title="a", summary="a", deadline=m.now(), deadline_evidence="编造的时间")

    monkeypatch.setattr("app.campus.provider", Fabricated)
    result = admin.post(API + "/announcements/extract", json={"content": "截止时间未明确"}).json()
    assert result["deadline"] is None
    assert admin.get(API + "/announcements").json()["total"] == 0


def test_reminders_idempotency_completion_and_withdrawal(clients):
    student, admin, _ = clients
    row = notice(admin)
    admin.post(API + f"/announcements/{row['id']}/publish")
    a = student.post(
        API + "/todos", json={"title": "到期提醒", "remind_at": (m.now() + timedelta(hours=1)).isoformat()}
    ).json()
    b = student.post(API + "/todos", json={"title": "已完成", "completed": True}).json()
    c = student.post(API + "/todos", json={"title": "撤回事项", "announcement_id": row["id"]}).json()
    admin.post(API + f"/announcements/{row['id']}/withdraw")
    with session() as db:
        for item in [a, b, c]:
            db.get(m.Todo, uuid.UUID(item["id"])).remind_at = m.now() - timedelta(minutes=1)
        db.commit()
    deliver_reminders()
    deliver_reminders()
    messages = student.get(API + "/notifications").json()["items"]
    assert len(messages) == 1 and messages[0]["todo_id"] == a["id"]
    assert student.get(API + "/todos/" + a["id"]).json()["reminded_at"]


def test_todo_permissions_and_invalid_reminders(clients):
    student, admin, other = clients
    assert (
        student.post(API + "/todos", json={"title": " ", "remind_at": m.now().isoformat()}).status_code == 422
    )
    assert (
        student.post(
            API + "/todos", json={"title": "a", "remind_at": (m.now() - timedelta(hours=1)).isoformat()}
        ).status_code
        == 422
    )
    assert (
        student.post(
            API + "/todos",
            json={
                "title": "a",
                "due_at": (m.now() + timedelta(hours=1)).isoformat(),
                "remind_at": (m.now() + timedelta(hours=2)).isoformat(),
            },
        ).status_code
        == 422
    )
    row = student.post(API + "/todos", json={"title": "待办"}).json()
    for client in [admin, other]:
        assert client.get(API + "/todos/" + row["id"]).status_code == 404
        assert client.put(API + "/todos/" + row["id"], json={"title": "修改"}).status_code == 404
        assert client.delete(API + "/todos/" + row["id"]).status_code == 404
    assert (
        student.put(API + "/todos/" + row["id"], json={"title": "待办", "completed": True}).status_code == 200
    )
    assert student.get(API + "/todos?completed=false").json()["total"] == 0


def test_withdrawn_reminders_do_not_block_other_due_tasks(clients):
    student, admin, _ = clients
    uid = uuid.UUID(student.get(API + "/auth/me").json()["id"])
    aid = uuid.UUID(admin.get(API + "/auth/me").json()["id"])
    with session() as db:
        for i in range(105):
            notice = m.Announcement(
                author_id=aid,
                title=str(i),
                category="教学",
                content="a",
                source_url="https://hut.edu.cn",
                status="withdrawn",
            )
            db.add(notice)
            db.flush()
            db.add(
                m.Todo(
                    user_id=uid,
                    announcement_id=notice.id,
                    title="撤回事项",
                    remind_at=m.now() - timedelta(minutes=1),
                )
            )
        db.add(m.Todo(user_id=uid, title="有效事项", remind_at=m.now() - timedelta(minutes=1)))
        db.commit()
    deliver_reminders()
    messages = student.get(API + "/notifications").json()["items"]
    assert len(messages) == 1 and messages[0]["content"] == "有效事项"


def test_personal_materials_are_isolated_even_from_admin(clients):
    student, admin, other = clients
    cid = course(student)
    data = upload(student, cid, "# PRIVATE-COURSE-ORCHID\n\n仅本人可见的数据库事务说明。")
    run = student.post(API + f"/courses/{cid}/study", json={"content": "数据库事务"}).json()
    assert run["answerable"] and run["citations"]
    source = run["citations"][0]
    assert student.get(API + "/sources/" + source["chunk_id"]).status_code == 200
    assert admin.get(API + "/documents").json()["total"] == 0
    for client in [admin, other]:
        assert client.get(API + f"/courses/{cid}/documents").status_code == 404
        assert client.post(API + f"/courses/{cid}/study", json={"kind": "outline"}).status_code == 404
        assert client.get(API + "/sources/" + source["chunk_id"]).status_code == 404
        assert client.delete(API + f"/courses/{cid}/documents/{data['document_id']}").status_code == 404
    assert admin.get(API + "/documents/" + data["document_id"]).status_code == 404
    assert admin.get(API + "/jobs/" + data["job_id"]).status_code == 404
    with session() as db:
        for user in db.scalars(select(m.User)):
            assert db.execute(allowed_query(user)).all() == []


def test_study_outline_practice_history_and_delete(clients):
    student, _, _ = clients
    cid = course(student)
    empty = student.post(API + f"/courses/{cid}/study", json={"kind": "outline"}).json()
    assert not empty["answerable"] and not empty["citations"]
    data = upload(student, cid)
    for kind in ["outline", "practice"]:
        response = student.post(API + f"/courses/{cid}/study", json={"kind": kind})
        assert response.status_code == 201, response.text
        run = response.json()
        assert run["answerable"] and run["model_mode"] == "mock"
        assert bool(run["exercises"]) == (kind == "practice")
        if kind == "practice":
            assert run["exercises"][0]["sources"][0] == run["citations"][0]["number"]
    other_course = course(student, "其他课程")
    assert not student.post(API + f"/courses/{other_course}/study", json={"kind": "outline"}).json()[
        "answerable"
    ]
    student.delete(API + f"/courses/{cid}/documents/{data['document_id']}")
    history = student.get(API + f"/courses/{cid}/study").json()
    assert all(not item["citations"] and not item["exercises"] for item in history["items"])


def test_personal_version_failure_retains_published_material(clients):
    student, _, _ = clients
    cid = course(student)
    data = upload(student, cid)
    run = student.post(API + f"/courses/{cid}/study", json={"content": "事务"}).json()
    old_source = run["citations"][0]["chunk_id"]
    path = API + f"/courses/{cid}/documents/{data['document_id']}"
    failed = student.post(path + "/versions", files={"file": ("bad.txt", b"\xff\xfe")}).json()
    asyncio.run(process_import(failed["job_id"]))
    assert student.get(API + f"/courses/{cid}/documents").json()["items"][0]["active_version_id"]
    retry = student.post(path + "/retry")
    assert retry.status_code == 200
    asyncio.run(process_import(retry.json()["job_id"]))
    upload(student, cid, "# 事务更新\n\n数据库事务通过原子性保证全部成功或全部失败。", data["document_id"])
    assert student.get(API + "/sources/" + old_source).status_code == 200
    assert student.get(API + f"/courses/{cid}/study").json()["items"][0]["answerable"]


def test_invalid_study_citation_not_persisted(clients, monkeypatch):
    student, _, _ = clients
    cid = course(student)
    upload(student, cid)

    class Invalid(MockProvider):
        async def study(self, kind, question, sources, history):
            return StudyOutput(answer="错误引用", answerable=True, sources=[999])

    monkeypatch.setattr("app.campus.provider", Invalid)
    response = student.post(API + f"/courses/{cid}/study", json={"content": "事务"})
    assert response.status_code == 502 and response.json()["code"] == "INVALID_CITATIONS"
    assert student.get(API + f"/courses/{cid}/study").json()["total"] == 0


def test_material_deleted_during_generation_is_rejected(clients, monkeypatch):
    student, _, _ = clients
    cid = course(student)
    data = upload(student, cid)

    class Deleting(MockProvider):
        async def study(self, kind, question, sources, history):
            with session() as db:
                db.get(m.Document, uuid.UUID(data["document_id"])).deleted = True
                db.commit()
            return await super().study(kind, question, sources, history)

    monkeypatch.setattr("app.campus.provider", Deleting)
    response = student.post(API + f"/courses/{cid}/study", json={"kind": "outline"})
    assert response.status_code == 409 and response.json()["code"] == "MATERIAL_CHANGED"
    assert student.get(API + f"/courses/{cid}/study").json()["total"] == 0
