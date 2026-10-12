import asyncio
import json
import uuid
from datetime import timedelta

from sqlalchemy import func, select

from app import models as m
from app.db import session
from app.errors import AppError
from app.jobs import process_import
from app.schemas import Answer

API = "/api/v1"


def upload(
    admin,
    name="guide.md",
    content="# VPN\n\nVPN 错误 809，先检查网络连接，然后重新连接。",
    visibility="public",
    document=None,
):
    path = f"/documents/{document}/versions" if document else "/documents"
    response = admin.post(
        API + path, files={"file": (name, content.encode())}, data={"visibility": visibility}
    )
    assert response.status_code in {200, 201}, response.text
    data = response.json()
    asyncio.run(process_import(data["job_id"]))
    return data


def ask(client, question="VPN 错误809怎么办？", conv=None):
    if not conv:
        conv = client.post(API + "/conversations").json()["id"]
    response = client.post(API + f"/conversations/{conv}/messages", json={"content": question})
    assert response.status_code == 200, response.text
    events = {}
    for block in response.text.split("\n\n"):
        if block.startswith("event:"):
            name, data = block.split("\n", 1)
            events[name[7:]] = json.loads(data[6:])
    assert "done" in events
    return conv, events


def test_complete_workflow_and_idempotency(clients):
    student, admin, other = clients
    upload(admin)
    conv, events = ask(student)
    answer = events["answer"]
    assert answer["answerable"] and answer["model_mode"] == "mock"
    source = answer["citations"][0]
    assert "809" in student.get(API + "/sources/" + source["chunk_id"]).json()["content"]
    draft = student.post(API + f"/conversations/{conv}/ticket-draft").json()
    payload = {k: draft[k] for k in ("title", "category", "description")}
    payload["draft_id"] = draft["id"]
    key = {"Idempotency-Key": "same-request"}
    ticket = student.post(API + "/tickets", json=payload, headers=key)
    assert ticket.status_code == 201, ticket.text
    id = ticket.json()["id"]
    assert student.post(API + "/tickets", json=payload, headers=key).json()["id"] == id
    assert (
        student.post(API + "/tickets", json=payload, headers={"Idempotency-Key": "another-key"}).json()["id"]
        == id
    )
    assert student.get(API + "/tickets").json()["total"] == 1
    assert (
        student.post(API + "/tickets", json={**payload, "title": "changed"}, headers=key).status_code == 409
    )
    assert other.get(API + "/tickets/" + id).status_code == 404
    assert other.get(API + "/conversations/" + conv).status_code == 404
    assert (
        student.post(API + f"/conversations/{conv}/messages", json={"content": "继续问"}).status_code == 409
    )
    assert student.patch(API + "/tickets/" + id + "/status", json={"status": "resolved"}).status_code == 409
    assert admin.patch(API + "/tickets/" + id + "/status", json={"status": "in_progress"}).status_code == 200
    assert (
        admin.post(
            API + "/tickets/" + id + "/replies", json={"content": "请重新连接 VPN，已检查服务状态。"}
        ).status_code
        == 201
    )
    assert admin.patch(API + "/tickets/" + id + "/status", json={"status": "resolved"}).status_code == 200
    assert student.patch(API + "/tickets/" + id + "/status", json={"status": "open"}).status_code == 200
    assert admin.patch(API + "/tickets/" + id + "/status", json={"status": "resolved"}).status_code == 200
    assert student.patch(API + "/tickets/" + id + "/status", json={"status": "closed"}).status_code == 200
    assert admin.post(API + "/tickets/" + id + "/replies", json={"content": "late"}).status_code == 409
    detail = student.get(API + "/tickets/" + id).json()
    assert len(detail["events"]) == 6 and len(detail["replies"]) == 1


def test_permissions_and_withdrawal(clients):
    student, admin, other = clients
    assert student.get(API + "/documents").status_code == 403
    assert student.post(API + "/documents", files={"file": ("x.txt", b"x")}).status_code == 403
    data = upload(admin, content="# 内部\n\nADMIN-ONLY-ORCHID VPN 管理员专用密码流程。", visibility="admin")
    conv, events = ask(student, "ADMIN-ONLY-ORCHID")
    assert not events["answer"]["answerable"] and not events["answer"]["citations"]
    _, events = ask(admin, "ADMIN-ONLY-ORCHID")
    chunk = events["answer"]["citations"][0]["chunk_id"]
    assert student.get(API + "/sources/" + chunk).status_code == 404
    public = upload(admin, name="public.md")
    conv, events = ask(student)
    chunk = events["answer"]["citations"][0]["chunk_id"]
    assert (
        admin.patch(
            API + "/documents/" + public["document_id"] + "/visibility", json={"visibility": "admin"}
        ).status_code
        == 200
    )
    assert student.get(API + "/sources/" + chunk).status_code == 404
    assert not student.get(API + "/conversations/" + conv).json()["messages"][-1]["answerable"]
    assert admin.delete(API + "/documents/" + data["document_id"]).status_code == 200
    assert not ask(admin, "ADMIN-ONLY-ORCHID")[1]["answer"]["answerable"]


def test_version_failure_retry_and_deduplication(clients):
    student, admin, _ = clients
    original = upload(admin)
    duplicate = upload(admin, document=original["document_id"])
    assert duplicate["job_id"] == original["job_id"]
    asyncio.run(process_import(original["job_id"]))
    failed = upload(admin, name="bad.docx", content="not docx", document=original["document_id"])
    detail = admin.get(API + "/documents/" + original["document_id"]).json()
    assert detail["active_version_id"] == original["version_id"]
    assert detail["versions"][0]["status"] == "failed"
    assert ask(student)[1]["answer"]["answerable"]
    retry = admin.post(API + "/documents/" + original["document_id"] + "/retry")
    assert retry.status_code == 200
    asyncio.run(process_import(failed["job_id"]))
    with session() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(m.Chunk)
                .where(m.Chunk.version_id == uuid.UUID(failed["version_id"]))
            )
            == 0
        )
    new = upload(admin, content="# VPN\n\nVPN 809 新版操作：先关闭代理。", document=original["document_id"])
    assert (
        admin.get(API + "/documents/" + original["document_id"]).json()["active_version_id"]
        == new["version_id"]
    )


def test_stale_worker_and_lost_lease(clients):
    _, admin, _ = clients
    data = admin.post(API + "/documents", files={"file": ("x.md", b"# VPN\n809")}).json()
    with session() as db:
        job = db.get(m.ImportJob, uuid.UUID(data["job_id"]))
        job.status = "embedding"
        job.attempts = 1
        job.lease_token = "old"
        job.heartbeat = m.now() - timedelta(hours=1)
        db.commit()
    from app.jobs import owned_job, recover

    recover()
    with session() as db:
        job = db.get(m.ImportJob, uuid.UUID(data["job_id"]))
        assert job.status == "queued" and job.lease_token is None
        try:
            owned_job(db, job.id, "old")
        except AppError as exc:
            assert exc.code == "JOB_LEASE_LOST"
        else:
            assert False, "stale lease accepted"
    asyncio.run(process_import(data["job_id"]))
    assert admin.get(API + "/jobs/" + data["job_id"]).json()["status"] == "ready"


def test_model_failure_and_invalid_citations(clients, monkeypatch):
    student, admin, _ = clients
    upload(admin)
    from app.providers import MockProvider

    async def fail(*args):
        raise AppError("MODEL_TIMEOUT", "服务超时", 503)

    monkeypatch.setattr(MockProvider, "answer", fail)
    assert ask(student)[1]["error"]["code"] == "MODEL_TIMEOUT"

    async def bad(*args):
        return Answer(answer="无依据", answerable=True, sources=[999])

    monkeypatch.setattr(MockProvider, "answer", bad)
    assert not ask(student)[1]["answer"]["answerable"]


def test_auth_origin_and_input_errors(clients):
    student, _, _ = clients
    assert (
        student.post(API + "/conversations", headers={"Origin": "https://attacker.invalid"}).status_code
        == 403
    )
    conv = student.post(API + "/conversations").json()["id"]
    assert student.post(API + f"/conversations/{conv}/messages", json={"content": " "}).status_code == 422
    assert (
        student.post(API + "/auth/login", json={"email": "none@example.test", "password": "bad"}).status_code
        == 401
    )
    student.post(API + "/auth/logout")
    r = student.get(API + "/conversations")
    assert r.status_code == 401 and r.json()["request_id"]


def test_redis_dispatch(database):
    import os

    import pytest
    from redis import Redis

    url = os.environ.get("TEST_REDIS_URL")
    if not url:
        pytest.skip("Set TEST_REDIS_URL for the real Redis/Celery dispatch test")
    from app.jobs import celery, import_document

    redis = Redis.from_url(url)
    assert redis.ping()
    queue = "campus-test-" + uuid.uuid4().hex
    celery.conf.broker_url = url
    try:
        import_document.apply_async(args=[str(uuid.uuid4())], queue=queue)
        assert redis.llen(queue) == 1
    finally:
        redis.delete(queue)
