import asyncio
import uuid

from sqlalchemy import select

from app import models as m
from app.course_materials import process_search
from app.db import session
from app.providers import MockProvider
from tests.test_campus_features import API, course, upload


def test_document_source_filter_before_pagination_and_real_provenance(clients):
    student, admin, other = clients
    cid = course(student)
    uploaded = upload(student, cid)["document_id"]
    with session() as db:
        # An uploaded document with an AI-looking name is still an upload.
        db.get(m.Document, uuid.UUID(uploaded)).name = "AI联网资料-用户笔记.md"
        db.commit()
    response = student.post(API + f"/courses/{cid}/material-search", json={"limit": 3})
    asyncio.run(process_search(response.json()["id"]))
    path = API + f"/courses/{cid}/documents"
    uploads = student.get(path, params={"source": "uploaded", "page_size": 1}).json()
    assert uploads["total"] == 1 and uploads["items"][0]["id"] == uploaded
    assert uploads["items"][0]["source"] == "uploaded"
    generated = student.get(path, params={"source": "ai", "page_size": 1}).json()
    assert generated["total"] == 3 and len(generated["items"]) == 1
    assert generated["items"][0]["source"] == "ai"
    page2 = student.get(path, params={"source": "ai", "page_size": 1, "page": 2}).json()
    assert page2["items"][0]["id"] != generated["items"][0]["id"]
    assert student.get(path).json()["total"] == 4
    assert student.get(path, params={"source": "invalid"}).status_code == 422
    for client in [admin, other]:
        assert client.get(path, params={"source": "ai"}).status_code == 404


def test_course_delete_retires_documents_jobs_history_and_preserves_other_courses(clients):
    student, admin, other = clients
    cid, keep = course(student), course(student, "保留课程")
    uploaded = upload(student, cid)["document_id"]
    kept = upload(student, keep)["document_id"]
    assert (
        student.post(API + f"/courses/{cid}/study", json={"kind": "outline", "content": "事务"}).status_code
        == 201
    )
    batch = student.post(API + f"/courses/{cid}/material-search", json={"limit": 2}).json()
    asyncio.run(process_search(batch["id"]))
    with session() as db:
        row = db.get(m.MaterialSearch, uuid.UUID(batch["id"]))
        generated = row.document_ids
        jobs = row.job_ids
        # Simulate import redelivery still queued when the course is removed.
        for id in jobs:
            job = db.get(m.ImportJob, uuid.UUID(id))
            job.status = "queued"
            db.get(m.DocumentVersion, job.version_id).status = "queued"
        db.commit()
    path = API + f"/courses/{cid}"
    for client in [admin, other]:
        assert client.delete(path).status_code == 404
    assert student.delete(path).status_code == 200
    assert student.delete(path).status_code == 404
    for endpoint in ["documents", "study", "material-search"]:
        assert student.get(path + "/" + endpoint).status_code == 404
    assert student.get(API + f"/courses/{keep}/documents/{kept}").status_code == 200
    assert student.get(API + "/courses").json()["total"] == 1
    with session() as db:
        assert db.get(m.Course, uuid.UUID(cid)) is None
        assert db.get(m.MaterialSearch, uuid.UUID(batch["id"])) is None
        assert not db.scalars(select(m.StudyRun).where(m.StudyRun.course_id == uuid.UUID(cid))).all()
        for id in [uploaded, *generated]:
            doc = db.get(m.Document, uuid.UUID(id))
            assert doc.deleted and doc.course_id is None
        for id in jobs:
            job = db.get(m.ImportJob, uuid.UUID(id))
            assert job.status == "failed" and job.lease_token is None
    # Queued redelivery cannot regenerate deleted course materials.
    asyncio.run(process_search(batch["id"]))


def test_delete_during_ai_search_prevents_late_publication(clients, monkeypatch):
    student, _, _ = clients
    cid = course(student)

    class DeleteWhileSearching(MockProvider):
        async def course_materials(self, *args):
            assert student.delete(API + f"/courses/{cid}").status_code == 200
            return await super().course_materials(*args)

    monkeypatch.setattr("app.course_materials.provider", DeleteWhileSearching)
    batch = student.post(API + f"/courses/{cid}/material-search", json={}).json()
    asyncio.run(process_search(batch["id"]))
    with session() as db:
        assert not db.scalars(select(m.Document)).all()
    assert student.get(API + "/courses").json()["total"] == 0
