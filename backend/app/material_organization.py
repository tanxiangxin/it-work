"""Lossless, previewable and reversible organization of existing AI materials."""

import math
import re
import uuid
from io import BytesIO

from fastapi import UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select, update

from app import models as m
from app.errors import AppError
from app.jobs import enqueue
from app.storage import storage


class OrganizationGroup(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    document_ids: list[uuid.UUID] = Field(min_length=1, max_length=50)


class OrganizationPlan(BaseModel):
    groups: list[OrganizationGroup] = Field(min_length=1, max_length=20)


def local_organization_plan(db, docs, originals, course_name):
    """Group stored local vectors and titles; no model/network call or new facts."""
    java = "java" in course_name.lower()
    modules = [
        ("Java 语法与面向对象", ["语法", "面向对象", "object", "接口", "抽象"]),
        ("Java 类的组织与访问控制", ["包与", "访问修饰", "静态", "内部类", "枚举"]),
        ("Java 集合与泛型", ["集合", "泛型"]),
        ("Java 文件输入输出与异常处理", ["i_o", "i/o", "文件操作", "异常处理"]),
    ]
    groups, vectors, sizes = [], {}, {}
    for doc in docs:
        chunks = db.scalars(
            select(m.Chunk).where(
                m.Chunk.version_id == doc.active_version_id, ~m.Chunk.heading.endswith("网页来源")
            )
        ).all()
        body = re.split(r"^##\s+网页来源\s*$", originals[str(doc.id)], maxsplit=1, flags=re.M)[0]
        sizes[doc.id] = len(re.sub(r"^> AI 联网整理资料[^\n]*\n?", "", body, flags=re.M).strip())
        if chunks:
            vector = [sum(float(c.embedding[i]) for c in chunks) / len(chunks) for i in range(1024)]
            norm = math.sqrt(sum(v * v for v in vector)) or 1
            vectors[doc.id] = [v / norm for v in vector]
        label = next(
            (
                label
                for label, words in modules
                if java and sizes[doc.id] < 600 and any(word in doc.name.lower() for word in words)
            ),
            None,
        )
        current = next((group for group in groups if group.title == label), None) if label else None
        if current and sum(sizes[i] for i in current.document_ids) + sizes[doc.id] <= 1800:
            current.document_ids.append(doc.id)
        else:
            groups.append(
                OrganizationGroup(
                    title=label or doc.name.removeprefix("AI联网资料-").removesuffix(".md"),
                    document_ids=[doc.id],
                )
            )
    if java:
        return groups
    while True:
        best = None
        for i, first in enumerate(groups):
            for j in range(i + 1, len(groups)):
                second = groups[j]
                ids = first.document_ids + second.document_ids
                if (
                    any(id not in vectors for id in ids)
                    or sum(sizes[id] for id in ids) > 1600
                    or any(sizes[id] >= 600 for id in ids)
                ):
                    continue
                similarity = sum(
                    sum(a * b for a, b in zip(vectors[x], vectors[y], strict=True))
                    for x in first.document_ids
                    for y in second.document_ids
                ) / (len(first.document_ids) * len(second.document_ids))
                if similarity >= 0.65 and (best is None or similarity > best[0]):
                    best = (similarity, i, j)
        if best is None:
            break
        _, i, j = best
        groups[i].document_ids.extend(groups[j].document_ids)
        if groups[i].title != groups[j].title:
            groups[i].title = (groups[i].title + "与" + groups[j].title)[:100]
        groups.pop(j)
    return groups


def demote_headings(text):
    lines, fence = [], None
    for line in text.splitlines(keepends=True):
        marker = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if marker:
            if fence is None:
                fence = marker[1]
            elif marker[1][0] == fence[0] and len(marker[1]) >= len(fence):
                fence = None
        elif fence is None:
            line = re.sub(r"^(#{1,5}) ", r"#\1 ", line)
        lines.append(line)
    return "".join(lines)


def organization_data(db, row):
    jobs = db.scalars(
        select(m.ImportJob).where(m.ImportJob.id.in_([uuid.UUID(i) for i in row.job_ids]))
    ).all()
    return {
        "id": str(row.id),
        "status": row.status,
        "groups": row.groups,
        "old_document_ids": row.old_document_ids,
        "new_document_ids": row.new_document_ids,
        "ready": sum(job.status == "ready" for job in jobs),
        "failed": sum(job.status == "failed" for job in jobs),
        "total": len(row.job_ids),
    }


async def prepare_organization(db, course, user, ids, groups=None):
    from app.main import add_version

    docs = db.scalars(
        select(m.Document)
        .where(
            m.Document.id.in_(ids),
            m.Document.course_id == course.id,
            m.Document.owner_id == user.id,
            m.Document.deleted.is_(False),
            m.Document.archived.is_(False),
        )
        .order_by(m.Document.created_at, m.Document.id)
    ).all()
    if len(docs) < 2:
        raise AppError("NO_SMALL_MATERIALS", "至少需要两份可整理的 AI 资料", 422)
    if len(docs) > 50:
        raise AppError("TOO_MANY_MATERIALS", "本次最多整理 50 份资料", 422)
    originals, versions = {}, {}
    for doc in docs:
        version = db.get(m.DocumentVersion, doc.active_version_id) if doc.active_version_id else None
        if not version or version.status != "ready" or not version.filename.lower().endswith(".md"):
            raise AppError("MATERIAL_NOT_READY", "请等待所有资料导入完成后再整理", 409)
        originals[str(doc.id)] = storage.path(version.storage_key).read_text(encoding="utf-8-sig")
        versions[str(doc.id)] = str(version.id)
    if groups is None:
        groups = local_organization_plan(db, docs, originals, course.name)
    assigned = [id for group in groups for id in group.document_ids]
    if len(assigned) != len(set(assigned)) or set(assigned) != {d.id for d in docs}:
        raise AppError("INVALID_ORGANIZATION", "整理方案没有完整且唯一地覆盖原资料", 502)
    if len(groups) >= len(docs):
        raise AppError("NO_MERGE_NEEDED", "未找到可合并的相关资料，原资料保持不变", 422)
    # Lock course first, then original documents; recheck after the model call.
    current = db.scalar(
        select(m.Course).where(m.Course.id == course.id, m.Course.user_id == user.id).with_for_update()
    )
    if not current:
        raise AppError("NOT_FOUND", "课程已删除", 404)
    previous = db.scalar(
        select(m.MaterialOrganization).where(
            m.MaterialOrganization.course_id == course.id, m.MaterialOrganization.status == "draft"
        )
    )
    if previous:
        return previous
    for doc in docs:
        current_doc = db.scalar(
            select(m.Document)
            .where(m.Document.id == doc.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            current_doc.deleted
            or current_doc.archived
            or str(current_doc.active_version_id) != versions[str(doc.id)]
        ):
            raise AppError("MATERIAL_CHANGED", "资料已变更，请重新整理", 409)
    row = m.MaterialOrganization(
        user_id=user.id,
        course_id=course.id,
        old_document_ids=[str(d.id) for d in docs],
        groups=[],
        new_document_ids=[],
        job_ids=[],
    )
    db.add(row)
    keys, jobs = [], []
    try:
        for group in groups:
            title = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", group.title).strip(". ")
            if not title:
                raise AppError("INVALID_ORGANIZATION", "章节标题为空", 502)
            bodies, references = [], []
            for id in group.document_ids:
                text = originals[str(id)]
                parts = re.split(r"^##\s+网页来源\s*$", text, maxsplit=1, flags=re.M)
                body = re.sub(r"^> AI 联网整理资料[^\n]*\n?", "", parts[0], flags=re.M).strip()
                # Demote headings while preserving every original sentence and example.
                body = demote_headings(body)
                bodies.append(body)
                if len(parts) > 1:
                    references.extend(line for line in parts[1].splitlines() if line.strip())
            content = (
                f"# {title}\n\n> AI 联网整理资料，按已有原文合并，未新增知识，仅供学习参考。\n\n"
                + "\n\n".join(bodies)
            )
            content += "\n\n## 网页来源\n\n" + "\n".join(dict.fromkeys(references)) + "\n"
            doc = m.Document(
                name=f"AI联网资料-{title}.md",
                visibility="private",
                owner_id=user.id,
                course_id=course.id,
                archived=True,
            )
            db.add(doc)
            db.flush()
            file = UploadFile(filename=doc.name, file=BytesIO(content.encode("utf-8")))
            try:
                job = await add_version(db, doc, file)
            finally:
                await file.close()
            keys.append(db.get(m.DocumentVersion, job.version_id).storage_key)
            jobs.append(job.id)
            row.groups = [
                *row.groups,
                {
                    "title": title,
                    "document_ids": [str(i) for i in group.document_ids],
                    "original_names": [next(d.name for d in docs if d.id == i) for i in group.document_ids],
                    "version_ids": {str(i): versions[str(i)] for i in group.document_ids},
                    "new_document_id": str(doc.id),
                    "new_version_id": str(job.version_id),
                },
            ]
            row.new_document_ids = [*row.new_document_ids, str(doc.id)]
            row.job_ids = [*row.job_ids, str(job.id)]
        db.commit()
    except BaseException:
        db.rollback()
        for key in keys:
            storage.remove(key)
        raise
    for id in jobs:
        enqueue(id)
    return row


def switch_organization(db, row, apply=True):
    if row.status != ("draft" if apply else "applied"):
        raise AppError("ORGANIZATION_STATE", "整理方案状态已变化，请刷新", 409)
    if apply:
        data = organization_data(db, row)
        if data["ready"] != data["total"] or data["failed"]:
            raise AppError("MATERIAL_NOT_READY", "请等待新资料全部导入成功后再应用", 409)
    docs = {
        str(d.id): d
        for d in db.scalars(
            select(m.Document)
            .where(m.Document.id.in_([uuid.UUID(i) for i in row.old_document_ids + row.new_document_ids]))
            .order_by(m.Document.id)
            .with_for_update()
        )
    }
    if any(i not in docs or docs[i].deleted for i in row.old_document_ids + row.new_document_ids):
        raise AppError("MATERIAL_CHANGED", "资料已删除，不能切换该方案", 409)
    if apply:
        for group in row.groups:
            if str(docs[group["new_document_id"]].active_version_id) != group["new_version_id"]:
                raise AppError("MATERIAL_CHANGED", "新资料已更新，请重新整理后再应用", 409)
            for id, version in group["version_ids"].items():
                if str(docs[id].active_version_id) != version or docs[id].archived:
                    raise AppError("MATERIAL_CHANGED", "原资料已变更，请重新整理", 409)
    for id in row.old_document_ids:
        docs[id].archived = apply
    for id in row.new_document_ids:
        docs[id].archived = not apply
    row.status = "applied" if apply else "rolled_back"
    db.execute(
        update(m.KnowledgeState)
        .where(m.KnowledgeState.id == 1)
        .values(generation=m.KnowledgeState.generation + 1)
    )
    db.commit()
    return organization_data(db, row)
