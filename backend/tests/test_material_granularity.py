import asyncio
import uuid

import pytest
from sqlalchemy import select

from app import models as m
from app.db import session
from app.jobs import process_import
from app.material_organization import OrganizationGroup, prepare_organization
from app.parsing import Section, chunk_sections, parse
from tests.test_campus_features import API, course, upload


def test_semantic_merge_preserves_headings_ranges_and_excludes_sources(tmp_path):
    path = tmp_path / "topic.md"
    path.write_text(
        "# 类的组织\n\n> AI 联网整理资料，仅供参考。\n\n## 包\n\n包用于组织类。\n\n## 访问修饰符\n\n控制访问范围。\n\n## 示例\n\n```python\n# 这是代码，不是标题\nprint(1)\n```\n\n## 网页来源\n\n- [网页](https://example.org/)",
        encoding="utf-8",
    )
    sections = parse(path, path.name)
    assert all("网页来源" not in s.heading for s in sections)
    assert all("仅供参考" not in s.content for s in sections)
    chunks = chunk_sections(sections)
    merged = next(c for c in chunks if "包用于组织类" in c.content)
    assert "控制访问范围" in merged.content
    assert {span["heading"] for span in merged.source_spans} == {"类的组织 / 包", "类的组织 / 访问修饰符"}
    assert any("# 这是代码，不是标题" in c.content and "print(1)" in c.content for c in chunks)
    assert not any("这是代码" in c.heading for c in chunks)
    assert all(len(c.content) <= 1200 for c in chunks)


def test_unrelated_chapters_never_merge():
    chunks = chunk_sections(
        [Section("包用于组织类。", "类的组织 / 包"), Section("事务具有原子性。", "数据库 / 事务")]
    )
    assert len(chunks) == 2


@pytest.mark.parametrize(
    "block", ["```java\n" + "int x = 1;\n" * 90 + "```", "| 列 | 值 |\n| --- | --- |\n" + "| A | B |\n" * 90]
)
def test_fitting_code_and_tables_remain_whole(block):
    text = "前文说明。" * 150 + "\n\n" + block + "\n\n后文说明。"
    chunks = chunk_sections([Section(text, "示例")])
    assert any(block in chunk.content for chunk in chunks)
    assert all(len(chunk.content) <= 1200 for chunk in chunks)


def test_version_policy_can_rebuild_same_original_without_hiding_old_version(clients, monkeypatch):
    from app.config import settings

    student, _, _ = clients
    cid = course(student)
    first = upload(student, cid)
    old_key = settings().index_key
    monkeypatch.setattr(settings(), "chunk_policy", "semantic-v3-test")
    second = upload(student, cid, document_id=first["document_id"])
    assert second["job_id"] != first["job_id"]
    assert settings().index_key == old_key
    with session() as db:
        versions = db.scalars(
            select(m.DocumentVersion).where(m.DocumentVersion.document_id == uuid.UUID(first["document_id"]))
        ).all()
        assert {v.chunk_policy for v in versions} == {
            "semantic-v2:1200:120:300",
            "semantic-v3-test:1200:120:300",
        }


def test_organization_preserves_code_comments_when_demoting_headings():
    from app.material_organization import demote_headings

    assert (
        demote_headings("# 章节\n```python\n# 代码注释\nprint(1)\n```\n## 小节\n")
        == "## 章节\n```python\n# 代码注释\nprint(1)\n```\n### 小节\n"
    )


def test_retrieval_removes_context_overlap_without_dropping_new_evidence():
    from app.retrieval import trim_context_overlap

    repeated = "原文的重叠段落。" * 10
    assert trim_context_overlap(repeated + "后续新知识", ["前文知识" + repeated]) == "后续新知识"
    assert trim_context_overlap("前文知识" + repeated, [repeated + "后续知识"]) == "前文知识"
    assert trim_context_overlap("独立知识点", ["其他内容"]) == "独立知识点"


def test_organization_lossless_private_applies_and_rolls_back_with_history(clients):
    student, admin, other = clients
    cid = course(student)
    legacy_ids = [
        upload(student, cid, content="# 数据库事务\n\n" + "事务具有原子性、一致性、隔离性和持久性。" * 8)[
            "document_id"
        ]
        for _ in range(3)
    ]
    with session() as db:
        owner = db.get(m.Course, uuid.UUID(cid)).user_id
        db.add(
            m.MaterialSearch(
                user_id=owner,
                course_id=uuid.UUID(cid),
                topic="",
                limit=3,
                status="complete",
                generation_done=True,
                document_ids=legacy_ids,
                job_ids=[],
            )
        )
        db.commit()
    path = API + f"/courses/{cid}/material-organization"
    for client in [admin, other]:
        assert client.post(path).status_code == 404
    old_docs = student.get(API + f"/courses/{cid}/documents?source=ai").json()["items"]
    before = student.post(API + f"/courses/{cid}/study", json={"kind": "outline", "content": ""}).json()
    response = student.post(path)
    assert response.status_code == 201, response.text
    organization = response.json()
    assert organization["total"] == 1 and organization["ready"] == 0
    apply = path + f"/{organization['id']}/apply"
    # Route has singular organization then id/action.
    assert student.post(apply).status_code == 409
    with session() as db:
        row = db.get(m.MaterialOrganization, uuid.UUID(organization["id"]))
        for job in row.job_ids:
            asyncio.run(process_import(job))
    preview = student.get(API + f"/courses/{cid}/documents/{organization['new_document_ids'][0]}").json()
    for old in old_docs:
        original = student.get(API + f"/courses/{cid}/documents/{old['id']}").json()["preview"]
        # Original sentences and references survive; only headings are demoted.
        assert original.split("\n\n", 1)[1].strip() in preview["preview"]
    assert len(student.get(API + f"/courses/{cid}/documents?source=ai").json()["items"]) == 3
    assert student.post(apply).status_code == 200
    assert student.get(API + f"/courses/{cid}/documents?source=ai").json()["total"] == 1
    history = student.get(API + f"/courses/{cid}/study").json()["items"]
    assert next(r for r in history if r["id"] == before["id"])["content"] == before["content"]
    assert all(student.get(API + f"/courses/{cid}/documents/{d['id']}").status_code == 200 for d in old_docs)
    for client in [admin, other]:
        assert client.post(apply).status_code == 404
    rollback = path + f"/{organization['id']}/rollback"
    assert student.post(rollback).status_code == 200
    assert student.get(API + f"/courses/{cid}/documents?source=ai").json()["total"] == 3


def test_invalid_organization_cannot_drop_or_duplicate_originals(clients):
    student, _, _ = clients
    cid = course(student)
    ids = [upload(student, cid)["document_id"] for _ in range(2)]
    with session() as db:
        course_row = db.get(m.Course, uuid.UUID(cid))
        user = db.get(m.User, course_row.user_id)
        with pytest.raises(Exception, match="覆盖原资料"):
            asyncio.run(
                prepare_organization(
                    db,
                    course_row,
                    user,
                    [uuid.UUID(i) for i in ids],
                    [OrganizationGroup(title="错误", document_ids=[uuid.UUID(ids[0])])],
                )
            )
