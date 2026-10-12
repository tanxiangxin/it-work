from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

NoticeCategory = Literal["教学", "学工", "招聘", "生活"]


def aware(value):
    if value is not None and value.tzinfo is None:
        raise ValueError("时间必须包含时区")
    return value


class NoticeInput(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    category: NoticeCategory
    content: str = Field(min_length=1, max_length=30000)
    summary: str = Field(default="", max_length=2000)
    source_url: HttpUrl
    audience: str = Field(default="", max_length=300)
    location: str = Field(default="", max_length=300)
    deadline: datetime | None = None
    _time = field_validator("deadline")(aware)

    @field_validator("source_url")
    @classmethod
    def official(cls, value):
        host = value.host or ""
        if host != "hut.edu.cn" and not host.endswith(".hut.edu.cn"):
            raise ValueError("仅支持湖南工业大学官方来源")
        return value

    @field_validator("title", "content")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("不能为空")
        return value.strip()


class NoticeExtractInput(BaseModel):
    content: str = Field(min_length=1, max_length=30000)


class NoticeExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(max_length=160)
    summary: str = Field(max_length=2000)
    audience: str = Field(default="", max_length=300)
    location: str = Field(default="", max_length=300)
    deadline: datetime | None = None
    deadline_evidence: str = Field(default="", max_length=300)
    _time = field_validator("deadline")(aware)


class SubscriptionsInput(BaseModel):
    categories: list[NoticeCategory] = Field(max_length=4)


class SavedInput(BaseModel):
    saved: bool


class TodoInput(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    notes: str = Field(default="", max_length=4000)
    announcement_id: UUID | None = None
    due_at: datetime | None = None
    remind_at: datetime | None = None
    completed: bool = False
    _time = field_validator("due_at", "remind_at")(aware)

    @field_validator("title")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("不能为空")
        return value.strip()


class CourseInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)

    @field_validator("name")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("不能为空")
        return value.strip()


class StudyInput(BaseModel):
    kind: Literal["question", "outline", "practice"] = "question"
    content: str = Field(default="", max_length=4000)


class Exercise(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["true_false", "short_answer"] = "short_answer"
    question: str = Field(min_length=1, max_length=1000)
    answer: str = Field(min_length=1, max_length=2000)
    explanation: str = Field(min_length=1, max_length=2000)
    sources: list[int] = Field(min_length=1, max_length=5)

    @field_validator("answer")
    @classmethod
    def judgment_answer(cls, value, info):
        if info.data.get("kind") == "true_false" and value not in {"正确", "错误"}:
            raise ValueError("判断题参考答案必须为正确或错误")
        return value


class PracticeSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answers: list[str] = Field(min_length=1, max_length=10)

    @field_validator("answers")
    @classmethod
    def completed(cls, values):
        if any(not value.strip() or len(value) > 4000 for value in values):
            raise ValueError("请填写每道题的答案，每题最多4000字")
        return [value.strip() for value in values]


class ExerciseGrade(BaseModel):
    model_config = ConfigDict(extra="forbid")
    number: int = Field(ge=1, le=10)
    score: int = Field(ge=0, le=10)
    correct: bool | None = None
    feedback: str = Field(min_length=1, max_length=2000)
    knowledge_points: list[str] = Field(min_length=1, max_length=20)
    criteria: list[dict] = Field(default_factory=list, max_length=5)

    @field_validator("knowledge_points")
    @classmethod
    def valid_points(cls, values):
        if any(not value.strip() or len(value) > 120 for value in values):
            raise ValueError("知识点不能为空且最多120字")
        return values


class PracticeGrade(BaseModel):
    model_config = ConfigDict(extra="forbid")
    results: list[ExerciseGrade] = Field(min_length=1, max_length=10)
    suggestions: list[str] = Field(min_length=1, max_length=10)

    @field_validator("suggestions")
    @classmethod
    def valid_suggestions(cls, values):
        if any(not value.strip() or len(value) > 1000 for value in values):
            raise ValueError("复习建议不能为空且最多1000字")
        return values


class StudyOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer: str = Field(min_length=1, max_length=12000)
    answerable: bool
    evidence_sufficient: bool | None = None
    sources: list[int] = Field(default_factory=list, max_length=20)
    exercises: list[Exercise] = Field(default_factory=list, max_length=10)


class WebSource(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    url: HttpUrl


class WebStudyOutput(BaseModel):
    answer: str = Field(min_length=1, max_length=12000)
    sources: list[WebSource] = Field(min_length=1, max_length=20)


class MaterialSearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topic: str = Field(default="", max_length=300)
    limit: int = Field(default=3, ge=1, le=10)


class GeneratedMaterial(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=3000)
    sources: list[int] = Field(min_length=1, max_length=20)


class MaterialCollection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    materials: list[GeneratedMaterial] = Field(default_factory=list, max_length=10)
