import pytest

from app.campus_schemas import Exercise, StudyOutput
from app.errors import AppError
from app.providers import CompatibleProvider, MockProvider
from tests.test_campus_features import API, course, upload


@pytest.mark.asyncio
@pytest.mark.parametrize("choices", [[None], ["invalid"], [{"message": None}], []])
async def test_malformed_completion_is_a_model_error(monkeypatch, choices):
    model = CompatibleProvider()

    async def request(*args, **kwargs):
        return {"choices": choices}

    monkeypatch.setattr(model, "request", request)
    with pytest.raises(AppError) as error:
        await model.general_answer("你好", [])
    assert error.value.code == "MODEL_OUTPUT"


def test_practice_rejects_wrong_question_mix_without_saving(clients, monkeypatch):
    student, _, _ = clients
    id = course(student)
    upload(student, id)

    async def study(self, kind, question, sources, history):
        return StudyOutput(
            answer="练习题",
            answerable=True,
            sources=[1],
            exercises=[
                Exercise(question=f"简答题{i}", answer="参考答案", explanation="讲解", sources=[1])
                for i in range(10)
            ],
        )

    monkeypatch.setattr(MockProvider, "study", study)
    response = student.post(f"{API}/courses/{id}/study", json={"kind": "practice"})
    assert response.status_code == 502 and response.json()["code"] == "MODEL_OUTPUT"
    assert student.get(f"{API}/courses/{id}/study").json()["total"] == 0
