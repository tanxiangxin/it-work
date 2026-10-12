import pytest

from app.errors import AppError
from app.providers import CompatibleProvider, MockProvider, insufficient_study_evidence
from tests.test_campus_features import API, course, upload


def search_result(url="https://www.postgresql.org/docs/current/tutorial-transactions.html"):
    return {
        "type": "web_search_tool_result",
        "content": [
            {"type": "web_search_result", "title": "Transactions", "url": url},
        ],
    }


def test_web_parser_requires_real_search_and_complete_answer():
    with pytest.raises(AppError):
        CompatibleProvider.parse_web_study({"content": None})
    payload = {
        "stop_reason": "end_turn",
        "content": [
            {"type": "text", "text": "将搜索"},
            search_result(),
            search_result(),
            {"type": "text", "text": "事务参考答案"},
        ],
    }
    result = CompatibleProvider.parse_web_study(payload)
    assert result.answer == "事务参考答案" and len(result.sources) == 1
    for blocks in [
        [],
        [{"type": "text", "text": "没有联网的答案"}],
        [search_result("javascript:alert(1)"), {"type": "text", "text": "答案"}],
        [{"type": "web_search_tool_result", "content": {"error_code": "unavailable"}}],
    ]:
        with pytest.raises(AppError):
            CompatibleProvider.parse_web_study({"stop_reason": "end_turn", "content": blocks})
    payload["stop_reason"] = "max_tokens"
    with pytest.raises(AppError):
        CompatibleProvider.parse_web_study(payload)


def test_study_falls_back_and_preserves_web_provenance(clients):
    student, _, _ = clients
    cid = course(student)
    path = API + f"/courses/{cid}/study"
    empty = student.post(path, json={"content": "量子纠缠"}).json()
    assert empty["answer_kind"] == "web" and empty["web_sources"]
    data = upload(student, cid)
    relevant = student.post(path, json={"content": "数据库事务"}).json()
    assert relevant["answer_kind"] == "knowledge" and relevant["citations"]
    unrelated = student.post(path, json={"content": "量子纠缠"}).json()
    assert unrelated["answer_kind"] == "web" and unrelated["answerable"]
    assert unrelated["citations"] == unrelated["exercises"] == []
    student.delete(API + f"/courses/{cid}/documents/{data['document_id']}")
    history = student.get(path).json()["items"]
    web_runs = [row for row in history if row["answer_kind"] == "web"]
    assert len(web_runs) == 2 and all(row["answerable"] and row["web_sources"] for row in web_runs)
    for kind in ["outline", "practice"]:
        row = student.post(path, json={"kind": kind}).json()
        assert not row["answerable"] and row["answer_kind"] == "knowledge"


def test_failed_search_is_not_saved_as_an_answer(clients, monkeypatch):
    student, _, _ = clients
    cid = course(student)

    class Failed(MockProvider):
        async def web_study(self, question):
            raise AppError("WEB_SEARCH_UNAVAILABLE", "搜索暂时不可用", 503)

    monkeypatch.setattr("app.campus.provider", Failed)
    path = API + f"/courses/{cid}/study"
    assert student.post(path, json={"content": "量子纠缠"}).status_code == 503
    assert student.get(path).json()["total"] == 0


def test_history_categories_filter_before_pagination(clients):
    student, _, _ = clients
    cid = course(student)
    upload(student, cid)
    path = API + f"/courses/{cid}/study"
    for kind in ["question", "question", "outline", "practice"]:
        assert student.post(path, json={"kind": kind, "content": "数据库事务"}).status_code == 201
    for kind, total in [("question", 2), ("outline", 1), ("practice", 1)]:
        result = student.get(path, params={"kind": kind, "page_size": 1}).json()
        assert result["total"] == total and len(result["items"]) == 1
        assert result["items"][0]["kind"] == kind
    assert student.get(path).json()["total"] == 4
    assert student.get(path, params={"kind": "invalid"}).status_code == 422


@pytest.mark.parametrize("explicit_flag", [False, None])
def test_partial_answer_with_true_flag_still_searches(clients, monkeypatch, explicit_flag):
    from app.campus_schemas import StudyOutput

    student, _, _ = clients
    cid = course(student)
    upload(student, cid)

    class Partial(MockProvider):
        async def study(self, kind, question, sources, history):
            return StudyOutput(
                answer="提供的资料没有给出 Java 的完整定义，只涉及相关课程主题，无法给出更完整的定义。"
                if explicit_flag is None
                else "资料只能支持部分内容。",
                answerable=True,
                evidence_sufficient=explicit_flag,
                sources=[sources[0]["number"]],
            )

    monkeypatch.setattr("app.campus.provider", Partial)
    response = student.post(API + f"/courses/{cid}/study", json={"content": "Java是什么"})
    assert response.status_code == 201
    row = response.json()
    assert row["answer_kind"] == "web" and row["web_sources"] and not row["citations"]
    assert "没有给出" not in row["content"]


def test_evidence_guard_does_not_mistake_technical_limitations_for_refusal():
    assert not insufficient_study_evidence("Java 类不能多继承，但可实现多个接口，资料明确介绍了这种机制。")
    assert not insufficient_study_evidence("统计资料中的数据不足会造成估计偏差，需要扩大样本量。")
    assert insufficient_study_evidence("现有资料不足以回答该问题，请补充资料。")
