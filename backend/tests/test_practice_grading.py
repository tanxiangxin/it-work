import json
import uuid

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app import models as m
from app.campus_schemas import ExerciseGrade, PracticeGrade, PracticeSubmission
from app.db import session
from app.providers import CompatibleProvider

API = "/api/v1"


def practice(student):
    course = student.post(API + "/courses", json={"name": "事务复习"}).json()["id"]
    with session() as db:
        user = db.scalar(select(m.User).where(m.User.email == "student@example.test"))
        row = m.StudyRun(
            user_id=user.id,
            course_id=uuid.UUID(course),
            kind="practice",
            question="事务练习",
            content="请作答",
            citations=[],
            answerable=True,
            model_mode="mock",
            exercises=[
                {
                    "kind": "true_false",
                    "question": "事务具有原子性",
                    "answer": "正确",
                    "explanation": "原子性保障整体提交",
                    "sources": [1],
                },
                {
                    "kind": "short_answer",
                    "question": "解释原子性",
                    "answer": "全部成功或全部失败",
                    "explanation": "不能部分提交",
                    "sources": [1],
                },
            ],
        )
        db.add(row)
        db.commit()
        run = str(row.id)
    return course, run, f"{API}/courses/{course}/study/{run}/submit"


def test_grading_persists_and_is_private(clients):
    student, admin, other = clients
    course, run, path = practice(student)
    for client in (admin, other):
        assert client.post(path, json={"answers": ["正确", "全部成功或全部失败"]}).status_code == 404
    assert student.post(path, json={"answers": ["正确"]}).status_code == 422
    assert student.post(path, json={"answers": ["正确", " "]}).status_code == 422
    response = student.post(path, json={"answers": ["错误", "全部成功或全部失败"]})
    assert response.status_code == 200, response.text
    grading = response.json()["grading"]
    assert grading["total_score"] == 10 and grading["max_score"] == 20
    assert grading["results"][0]["correct"] is False
    assert grading["results"][1]["correct"] is None
    assert grading["suggestions"]
    saved = student.get(f"{API}/courses/{course}/study?kind=practice").json()["items"][0]
    assert saved["grading"] == grading
    updated = student.post(path, json={"answers": ["正确", "全部成功或全部失败"]}).json()
    assert updated["grading"]["total_score"] == 20
    different_course = student.post(API + "/courses", json={"name": "另一个课程"}).json()["id"]
    assert (
        student.post(
            f"{API}/courses/{different_course}/study/{run}/submit", json={"answers": ["正确", "回答"]}
        ).status_code
        == 404
    )


@pytest.mark.parametrize("numbers,scores", [([2, 1], [10, 10]), ([1, 2], [5, 10]), ([1], [10])])
def test_invalid_grading_does_not_save(clients, monkeypatch, numbers, scores):
    student, _, _ = clients
    course, _, path = practice(student)

    class InvalidModel:
        calls = 0
        usage = None

        async def grade_practice(self, exercises, answers):
            return PracticeGrade(
                results=[
                    ExerciseGrade(
                        number=n,
                        score=s,
                        correct=True if n == 1 else None,
                        feedback="评分",
                        knowledge_points=["原子性"],
                    )
                    for n, s in zip(numbers, scores, strict=True)
                ],
                suggestions=["复习原子性"],
            )

    monkeypatch.setattr("app.campus.provider", InvalidModel)
    response = student.post(path, json={"answers": ["正确", "回答"]})
    assert response.status_code == 502, response.text
    assert student.get(f"{API}/courses/{course}/study").json()["items"][0]["grading"] == {}


def test_non_practice_cannot_be_graded(clients):
    student, _, _ = clients
    _, run, path = practice(student)
    with session() as db:
        db.get(m.StudyRun, uuid.UUID(run)).kind = "outline"
        db.commit()
    assert student.post(path, json={"answers": ["正确", "回答"]}).status_code == 409


def test_submission_limits():
    for values in ([""], ["a" * 4001], ["a"] * 11):
        with pytest.raises(ValidationError):
            PracticeSubmission(answers=values)


@pytest.mark.asyncio
async def test_real_grading_uses_server_exercises(monkeypatch):
    captured = {}
    model = CompatibleProvider()

    async def structured(prompt, payload, schema, **kwargs):
        from app.practice_grading import Rubrics

        assert "指令" in prompt
        if schema is Rubrics:
            captured.update(payload)
            assert "answers" not in payload
            return schema(
                rubrics=[
                    {
                        "number": 1,
                        "criteria": [
                            {"number": 1, "description": "原子性", "points": 7, "core": True},
                            {"number": 2, "description": "隔离性", "points": 3, "core": False},
                        ],
                    }
                ]
            )
        return schema(
            results=[
                {
                    "number": 1,
                    "criteria": [
                        {"number": 1, "status": "full", "quote": "只回答原子性", "reason": "覆盖原子性"},
                        {"number": 2, "status": "missing", "quote": "", "reason": "遗漏隔离性"},
                    ],
                }
            ],
            suggestions=["复习隔离性"],
        )

    monkeypatch.setattr(model, "structured", structured)
    result = await model.grade_practice([{"question": "解释事务", "answer": "ACID"}], ["只回答原子性"])
    assert captured["exercises"][0]["answer"] == "ACID"
    assert result.results[0].score == 7


def grade_payload(point_count=6):
    return {
        "results": [
            {
                "number": 1,
                "score": 3,
                "correct": None,
                "feedback": "只解释了运行时异常，未说明异常分类及finally。",
                "knowledge_points": [f"异常知识点{i + 1}" for i in range(point_count)],
            }
        ],
        "suggestions": [f"复习建议{i + 1}" for i in range(6)],
    }


def test_six_knowledge_points_and_suggestions_are_valid():
    grade = PracticeGrade.model_validate(grade_payload())
    assert len(grade.results[0].knowledge_points) == 6
    assert len(grade.suggestions) == 6
    bad_score = grade_payload()
    bad_score["results"][0]["score"] = 11
    with pytest.raises(ValidationError):
        PracticeGrade.model_validate(bad_score)


@pytest.mark.asyncio
async def test_grading_retries_format_once_with_schema(monkeypatch):
    model = CompatibleProvider()
    requests = []

    async def request(base, key, path, payload):
        requests.append(json.loads(json.dumps(payload)))
        content = grade_payload(21 if len(requests) == 1 else 6)
        return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(content)}}]}

    monkeypatch.setattr(model, "request", request)
    result = await model.structured(
        "评分格式测试", {"answer": "运行时异常"}, PracticeGrade, validation_retries=1
    )
    assert len(requests) == 2
    assert len(result.results[0].knowledge_points) == 6
    repair = requests[1]["messages"][0]["content"]
    assert '"maxItems": 20' in repair
    assert "knowledge_points" in repair
    assert "运行时异常" not in repair
    assert requests[1]["messages"][1] == requests[0]["messages"][1]


@pytest.mark.asyncio
async def test_grading_format_retry_is_bounded(monkeypatch):
    from app.errors import AppError

    model = CompatibleProvider()
    requests = []

    async def request(base, key, path, payload):
        requests.append(True)
        content = grade_payload()
        content["results"][0]["score"] = 99
        return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(content)}}]}

    monkeypatch.setattr(model, "request", request)
    with pytest.raises(AppError) as error:
        await model.structured("评分格式测试", {"answer": "运行时异常"}, PracticeGrade, validation_retries=1)
    assert error.value.code == "MODEL_OUTPUT"
    assert len(requests) == 2


def test_rubric_requires_student_evidence_and_limits_core_errors():
    from app.practice_grading import Evaluation, Rubric, combine

    rubric = Rubric(
        number=1,
        criteria=[
            {"number": 1, "description": "重载参数不同", "points": 8, "core": True},
            {"number": 2, "description": "重写涉及继承", "points": 2, "core": True},
        ],
    )
    invented = Evaluation(
        number=1,
        criteria=[
            {"number": 1, "status": "full", "quote": "参数不同", "reason": "正确"},
            {"number": 2, "status": "full", "quote": "继承", "reason": "正确"},
        ],
    )
    assert combine(rubric, invented, invented, "没有区别").score == 0
    contradictory = Evaluation(
        number=1,
        criteria=[
            {"number": 1, "status": "full", "quote": "参数不同", "reason": "正确"},
            {"number": 2, "status": "contradicted", "quote": "重写不涉及继承", "reason": "核心结论相反"},
        ],
    )
    result = combine(rubric, contradictory, contradictory, "参数不同，重写不涉及继承")
    assert result.score == 2
    assert "最多2分" in result.feedback
    missing = Evaluation(
        number=1,
        criteria=[
            {"number": 1, "status": "missing", "quote": "", "reason": "未回答"},
            {"number": 2, "status": "missing", "quote": "", "reason": "未回答"},
        ],
    )
    assert combine(rubric, invented, missing, "参数不同，继承").score == 0


@pytest.mark.asyncio
async def test_judgment_uses_reference_without_model():
    model = CompatibleProvider()
    grade = await model.grade_practice(
        [{"kind": "true_false", "question": "Java支持类多继承", "answer": "错误", "explanation": "类单继承"}],
        ["对"],
    )
    assert grade.results[0].score == 0 and grade.results[0].correct is False
    assert model.calls == 0


def test_ten_answers_persist_with_total_100(clients):
    student, _, _ = clients
    _, run, path = practice(student)
    with session() as db:
        row = db.get(m.StudyRun, uuid.UUID(run))
        row.exercises = row.exercises * 5
        db.commit()
    response = student.post(path, json={"answers": ["正确", "全部成功或全部失败"] * 5})
    assert response.status_code == 200, response.text
    grade = response.json()["grading"]
    assert grade["total_score"] == grade["max_score"] == 100
    assert [r["number"] for r in grade["results"]] == list(range(1, 11))


@pytest.mark.asyncio
async def test_ten_short_answers_are_graded_in_bounded_batches(monkeypatch):
    from app.practice_grading import Rubrics

    model = CompatibleProvider()
    sizes = []

    async def structured(prompt, payload, schema, **kwargs):
        sizes.append(len(payload["exercises"]))
        if schema is Rubrics:
            return schema(
                rubrics=[
                    {
                        "number": ex["number"],
                        "criteria": [
                            {"number": 1, "description": "正确解释原子性", "points": 10, "core": True}
                        ],
                    }
                    for ex in payload["exercises"]
                ]
            )
        return schema(
            results=[
                {
                    "number": ex["number"],
                    "criteria": [
                        {"number": 1, "status": "full", "quote": "全部成功或全部失败", "reason": "正确"}
                    ],
                }
                for ex in payload["exercises"]
            ],
            suggestions=[f"复习第{payload['exercises'][0]['number']}题相关知识"],
        )

    monkeypatch.setattr(model, "structured", structured)
    grade = await model.grade_practice(
        [{"kind": "short_answer", "question": "解释原子性", "answer": "全部成功或全部失败"}] * 10,
        ["全部成功或全部失败"] * 10,
    )
    assert len(grade.results) == 10 and all(r.score == 10 for r in grade.results)
    assert len(sizes) == 12 and max(sizes) == 3
    assert len(grade.suggestions) == 4
