import asyncio
import uuid
from datetime import timedelta

from sqlalchemy import select

from app import models as m
from app.campus_schemas import GeneratedMaterial, MaterialCollection, WebSource
from app.course_materials import process_search, recover_searches
from app.db import session
from app.errors import AppError
from app.jobs import process_import
from app.providers import MockProvider
from tests.test_campus_features import API, course


def test_search_cap_import_repeat_and_permissions(clients):
    student, admin, other = clients
    cid = course(student)
    path = API + f"/courses/{cid}/material-search"
    assert student.get(path).json() == {"job": None}
    for limit in [0, 11]:
        assert student.post(path, json={"limit": limit}).status_code == 422
    for client in [admin, other]:
        assert client.post(path, json={}).status_code == 404
        assert client.get(path).status_code == 404
    for batch in range(2):
        response = student.post(path, json={"limit": 10})
        assert response.status_code == 202
        id = response.json()["id"]
        assert student.post(path, json={}).status_code == 409
        asyncio.run(process_search(id))
        assert student.get(path).json()["job"]["generated"] == 10
        assert student.get(path).json()["job"]["generation_done"]
        with session() as db:
            row = db.get(m.MaterialSearch, uuid.UUID(id))
            jobs = row.job_ids
            docs = db.scalars(
                select(m.Document).where(m.Document.id.in_([uuid.UUID(id) for id in row.document_ids]))
            ).all()
            assert all(doc.visibility == "private" and str(doc.course_id) == cid for doc in docs)
            doc_id = str(docs[0].id)
            version = db.scalar(select(m.DocumentVersion).where(m.DocumentVersion.document_id == docs[0].id))
            from app.storage import storage

            text = storage.path(version.storage_key).read_text()
            assert "AI 联网整理资料" in text and "https://example.org/" in text
        detail_path = API + f"/courses/{cid}/documents/{doc_id}"
        pending = student.get(detail_path).json()
        assert "AI 联网整理资料" in pending["preview"]
        for client in [admin, other]:
            assert client.get(detail_path).status_code == 404
        for job in jobs:
            asyncio.run(process_import(job))
        result = student.get(path).json()["job"]
        assert result["status"] == "complete" and result["ready"] == 10
        detail = student.get(detail_path).json()
        assert detail["chunks"] and detail["chunk_total"] > 0
        assert detail["content_format"] == "markdown" and "## 网页来源" in detail["preview"]
        assert all(not chunk["heading"].endswith("网页来源") for chunk in detail["chunks"])
        # Redelivery must not create another batch.
        asyncio.run(process_search(id))
        assert student.get(API + f"/courses/{cid}/documents").json()["total"] == (batch + 1) * 10
    assert admin.get(API + "/documents").json()["total"] == 0


def test_requested_limit_is_enforced_even_if_model_returns_more(clients, monkeypatch):
    student, _, _ = clients
    cid = course(student)

    class TooMany(MockProvider):
        async def course_materials(self, course, topic, limit, existing):
            return await super().course_materials(course, topic, 10, existing)

    monkeypatch.setattr("app.course_materials.provider", TooMany)
    path = API + f"/courses/{cid}/material-search"
    id = student.post(path, json={"limit": 3}).json()["id"]
    asyncio.run(process_search(id))
    assert student.get(path).json()["job"]["generated"] == 3
    assert student.get(API + f"/courses/{cid}/documents").json()["total"] == 3


def test_bad_web_sources_and_failed_search_do_not_store_materials(clients, monkeypatch):
    student, _, _ = clients
    cid = course(student)
    path = API + f"/courses/{cid}/material-search"

    class Invalid(MockProvider):
        async def course_materials(self, *args):
            return MaterialCollection(
                materials=[GeneratedMaterial(title="伪造", content="错误", sources=[999])]
            ), [WebSource(title="来源", url="https://example.org/")]

    class Failed(MockProvider):
        async def course_materials(self, *args):
            raise AppError("WEB_SEARCH_UNAVAILABLE", "搜索暂时不可用", 503)

    for model in [Invalid, Failed]:
        monkeypatch.setattr("app.course_materials.provider", model)
        id = student.post(path, json={}).json()["id"]
        asyncio.run(process_search(id))
        assert student.get(path).json()["job"]["status"] == "failed"
        assert student.get(API + f"/courses/{cid}/documents").json()["total"] == 0


def test_interrupted_worker_releases_batch_for_retry(clients):
    student, _, _ = clients
    cid = course(student)
    path = API + f"/courses/{cid}/material-search"
    id = student.post(path, json={}).json()["id"]
    with session() as db:
        row = db.get(m.MaterialSearch, uuid.UUID(id))
        row.status, row.lease_token, row.started_at = "generating", "lost", m.now() - timedelta(minutes=11)
        db.commit()
    recover_searches()
    assert student.get(path).json()["job"]["status"] == "failed"
    assert student.post(path, json={}).status_code == 202


def test_failed_batch_rolls_back_documents_and_files(clients, monkeypatch):
    from app.config import settings
    from app.main import add_version

    student, _, _ = clients
    cid = course(student)
    path = API + f"/courses/{cid}/material-search"
    id = student.post(path, json={"limit": 2}).json()["id"]
    calls = 0

    async def fail_second(db, doc, file):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise AppError("STORAGE_UNAVAILABLE", "存储失败，请重试", 503)
        return await add_version(db, doc, file)

    monkeypatch.setattr("app.main.add_version", fail_second)
    asyncio.run(process_search(id))
    assert student.get(path).json()["job"]["status"] == "failed"
    assert student.get(API + f"/courses/{cid}/documents").json()["total"] == 0
    assert list(settings().storage_dir.iterdir()) == []
