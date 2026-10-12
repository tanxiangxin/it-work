import asyncio

import pytest

from app.campus_schemas import GeneratedMaterial, MaterialCollection, WebSource, WebStudyOutput
from app.course_materials import process_search
from app.errors import AppError
from app.providers import CompatibleProvider, MockProvider
from tests.test_campus_features import API, course


def test_complete_chapter_preserves_more_than_five_web_references():
    chapter = GeneratedMaterial(title="完整章节", content="正文", sources=list(range(1, 10)))
    assert chapter.sources == list(range(1, 10))


@pytest.mark.asyncio
async def test_native_batches_share_search_and_have_separate_output_budget(monkeypatch):
    model = CompatibleProvider()
    searches, sizes = [], []

    async def search(question, max_uses):
        searches.append(max_uses)
        return WebStudyOutput(
            answer="完整章节依据", sources=[WebSource(title="依据", url="https://example.org/")]
        )

    async def structured(system, data, schema, max_tokens):
        assert "800到1600" in system and max_tokens == 8192
        sizes.append(data["limit"])
        start = len(data["generated"])
        return MaterialCollection(
            materials=[
                GeneratedMaterial(
                    title=f"主题{start + i}",
                    content=(f"完整主题{start + i}的相关概念与示例。" * 70),
                    sources=[1],
                )
                for i in range(data["limit"])
            ]
        )

    monkeypatch.setattr(model, "web_study", search)
    monkeypatch.setattr(model, "structured", structured)
    batches = [batch async for batch, _ in model.material_batches("课程", "", 7, [])]
    assert searches == [1] and sizes == [3, 3, 1]
    assert [len(batch.materials) for batch in batches] == [3, 3, 1]


@pytest.mark.asyncio
async def test_insufficient_evidence_gets_only_one_additional_search(monkeypatch):
    model = CompatibleProvider()
    calls = 0

    async def search(*args, **kwargs):
        nonlocal calls
        calls += 1
        return WebStudyOutput(
            answer="只有简单定义", sources=[WebSource(title="依据", url="https://example.org/")]
        )

    async def structured(*args, **kwargs):
        return MaterialCollection(materials=[])

    monkeypatch.setattr(model, "web_study", search)
    monkeypatch.setattr(model, "structured", structured)
    assert [batch async for batch in model.material_batches("课程", "", 10, [])] == []
    assert calls == 2


def test_later_batch_failure_keeps_ready_materials_and_releases_search(clients, monkeypatch):
    student, _, _ = clients
    cid = course(student)

    class Partial(MockProvider):
        async def material_batches(self, course, topic, limit, existing):
            yield await self.course_materials(course, topic, 3, existing)
            raise AppError("MODEL_TIMEOUT", "后续批次超时", 503)

    monkeypatch.setattr("app.course_materials.provider", Partial)
    path = API + f"/courses/{cid}/material-search"
    batch = student.post(path, json={"limit": 7}).json()
    asyncio.run(process_search(batch["id"]))
    result = student.get(path).json()["job"]
    assert result["status"] == "partial" and result["ready"] == result["generated"] == 3
    assert result["generation_done"] and "超时" in result["error"]
    assert student.get(API + f"/courses/{cid}/documents?source=ai").json()["total"] == 3
    assert student.post(path, json={}).status_code == 202


@pytest.mark.asyncio
async def test_truncated_json_is_rejected_even_if_it_parses(monkeypatch):
    model = CompatibleProvider()

    async def request(*args, **kwargs):
        return {"choices": [{"finish_reason": "length", "message": {"content": '{"materials":[]}'}}]}

    monkeypatch.setattr(model, "request", request)
    with pytest.raises(AppError) as error:
        await model.structured("", {}, MaterialCollection, max_tokens=8192)
    assert error.value.code == "MODEL_OUTPUT_TRUNCATED"
