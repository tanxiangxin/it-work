import uuid
from datetime import UTC, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def now():
    return datetime.now(UTC)


class Record:
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class User(Record, Base):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(255), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    role: Mapped[str] = mapped_column(String(16))
    password_hash: Mapped[str] = mapped_column(Text)


class LoginSession(Record, Base):
    __tablename__ = "login_sessions"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AIConfiguration(Base):
    __tablename__ = "ai_configurations"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    mode: Mapped[str] = mapped_column(String(16))
    api_base: Mapped[str] = mapped_column(String(2048))
    model: Mapped[str] = mapped_column(String(200))
    api_key: Mapped[str] = mapped_column(Text, default="")
    api_style: Mapped[str] = mapped_column(String(16), default="openai")


class KnowledgeState(Base):
    __tablename__ = "knowledge_state"
    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    generation: Mapped[int] = mapped_column(default=0)


class Document(Record, Base):
    __tablename__ = "documents"
    name: Mapped[str] = mapped_column(String(255))
    visibility: Mapped[str] = mapped_column(String(16), default="public")
    active_version_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    course_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("courses.id"), nullable=True, index=True)


class DocumentVersion(Record, Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "file_hash", "index_key", "chunk_policy", name="uq_version_policy"),
    )
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(255))
    file_hash: Mapped[str] = mapped_column(String(64))
    index_key: Mapped[str] = mapped_column(String(100))
    chunk_policy: Mapped[str] = mapped_column(String(64), default="semantic-v2", server_default="legacy-v1")
    status: Mapped[str] = mapped_column(String(20), default="queued")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class Chunk(Record, Base):
    __tablename__ = "chunks"
    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("document_versions.id"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    heading: Mapped[str] = mapped_column(Text, default="")
    page: Mapped[int | None] = mapped_column(nullable=True)
    paragraph: Mapped[int | None] = mapped_column(nullable=True)
    source_spans: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    embedding: Mapped[list[float]] = mapped_column(Vector(1024))
    __table_args__ = (UniqueConstraint("version_id", "ordinal"),)


class ImportJob(Record, Base):
    __tablename__ = "import_jobs"
    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("document_versions.id"), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    attempts: Mapped[int] = mapped_column(default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    heartbeat: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_token: Mapped[str | None] = mapped_column(String(36), nullable=True)


class Conversation(Record, Base):
    __tablename__ = "conversations"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(120), default="新的问题")
    mode: Mapped[str] = mapped_column(String(16), default="bot")
    recent_hidden: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    history_hidden: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class Message(Record, Base):
    __tablename__ = "messages"
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversations.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="complete")
    model_mode: Mapped[str] = mapped_column(String(16), default="mock")
    citations: Mapped[list] = mapped_column(JSON, default=list)
    answerable: Mapped[bool] = mapped_column(Boolean, default=False)
    answer_kind: Mapped[str] = mapped_column(String(16), default="knowledge", server_default="knowledge")


class TicketDraft(Record, Base):
    __tablename__ = "ticket_drafts"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversations.id"), unique=True)
    title: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(20))
    description: Mapped[str] = mapped_column(Text)
    submitted: Mapped[bool] = mapped_column(Boolean, default=False)


class Ticket(Record, Base):
    __tablename__ = "tickets"
    __table_args__ = (UniqueConstraint("user_id", "idempotency_key"),)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    draft_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ticket_drafts.id"), unique=True)
    title: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(20))
    description: Mapped[str] = mapped_column(Text)
    location: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(20), default="open")
    idempotency_key: Mapped[str] = mapped_column(String(120))
    request_hash: Mapped[str] = mapped_column(String(64))
    sources: Mapped[list] = mapped_column(JSON, default=list)


class TicketReply(Record, Base):
    __tablename__ = "ticket_replies"
    ticket_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tickets.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    content: Mapped[str] = mapped_column(Text)


class TicketEvent(Record, Base):
    __tablename__ = "ticket_events"
    ticket_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tickets.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    before: Mapped[str | None] = mapped_column(String(20), nullable=True)
    after: Mapped[str] = mapped_column(String(20))


class RequestTrace(Record, Base):
    __tablename__ = "request_traces"
    request_id: Mapped[str] = mapped_column(String(36), index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    operation: Mapped[str] = mapped_column(String(32), default="question", server_default="question")
    model_mode: Mapped[str] = mapped_column(String(16))
    model: Mapped[str] = mapped_column(String(100))
    duration_ms: Mapped[int] = mapped_column(Integer)
    calls: Mapped[int] = mapped_column(Integer)
    usage: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(20))


class Notification(Record, Base):
    __tablename__ = "notifications"
    __table_args__ = (UniqueConstraint("user_id", "event_id"),)
    sequence: Mapped[int] = mapped_column(BigInteger, Identity(), unique=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    ticket_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tickets.id"), nullable=True)
    announcement_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("announcements.id"), nullable=True)
    todo_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("todos.id"), nullable=True)
    study_job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("study_jobs.id"), nullable=True)
    event_id: Mapped[uuid.UUID] = mapped_column()
    kind: Mapped[str] = mapped_column(String(24))
    title: Mapped[str] = mapped_column(String(160))
    content: Mapped[str] = mapped_column(Text)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Announcement(Record, Base):
    __tablename__ = "announcements"
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(160))
    category: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text, default="")
    source_url: Mapped[str] = mapped_column(Text)
    audience: Mapped[str] = mapped_column(String(300), default="")
    location: Mapped[str] = mapped_column(String(300), default="")
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="draft")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Subscription(Record, Base):
    __tablename__ = "subscriptions"
    __table_args__ = (UniqueConstraint("user_id", "category"),)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    category: Mapped[str] = mapped_column(String(16))


class SavedAnnouncement(Record, Base):
    __tablename__ = "saved_announcements"
    __table_args__ = (UniqueConstraint("user_id", "announcement_id"),)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    announcement_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("announcements.id"))


class Todo(Record, Base):
    __tablename__ = "todos"
    __table_args__ = (UniqueConstraint("user_id", "announcement_id"),)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    announcement_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("announcements.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(160))
    notes: Mapped[str] = mapped_column(Text, default="")
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    remind_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    reminded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Course(Record, Base):
    __tablename__ = "courses"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))


class StudyRun(Record, Base):
    __tablename__ = "study_runs"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    question: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    citations: Mapped[list] = mapped_column(JSON, default=list)
    exercises: Mapped[list] = mapped_column(JSON, default=list)
    grading: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    answerable: Mapped[bool] = mapped_column(Boolean, default=False)
    model_mode: Mapped[str] = mapped_column(String(16))
    answer_kind: Mapped[str] = mapped_column(String(16), default="knowledge", server_default="knowledge")
    web_sources: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")


class StudyJob(Record, Base):
    __tablename__ = "study_jobs"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="queued")
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("study_runs.id"), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    lease_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MaterialSearch(Record, Base):
    __tablename__ = "material_searches"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id"), index=True)
    topic: Mapped[str] = mapped_column(String(300), default="")
    limit: Mapped[int] = mapped_column(Integer, default=10)
    status: Mapped[str] = mapped_column(String(16), default="queued")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    lease_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    document_ids: Mapped[list] = mapped_column(JSON, default=list)
    job_ids: Mapped[list] = mapped_column(JSON, default=list)
    generation_done: Mapped[bool] = mapped_column(Boolean, default=False, server_default="true")
    timings: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")


class MaterialOrganization(Record, Base):
    __tablename__ = "material_organizations"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="draft")
    groups: Mapped[list] = mapped_column(JSON, default=list)
    old_document_ids: Mapped[list] = mapped_column(JSON, default=list)
    new_document_ids: Mapped[list] = mapped_column(JSON, default=list)
    job_ids: Mapped[list] = mapped_column(JSON, default=list)
