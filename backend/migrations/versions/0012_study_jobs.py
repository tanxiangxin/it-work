"""Durable learning generation and grading jobs with completion notifications."""

import sqlalchemy as sa
from alembic import op

revision = "0012_study_jobs"
down_revision = "0011_conversation_history"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "study_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("course_id", sa.Uuid(), sa.ForeignKey("courses.id"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("study_runs.id"), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("lease_token", sa.String(36), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_study_jobs_user_id", "study_jobs", ["user_id"])
    op.create_index("ix_study_jobs_course_id", "study_jobs", ["course_id"])
    op.create_index(
        "uq_study_jobs_active_course",
        "study_jobs",
        ["course_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )
    op.add_column("notifications", sa.Column("study_job_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_notification_study_job", "notifications", "study_jobs", ["study_job_id"], ["id"]
    )


def downgrade():
    op.drop_constraint("fk_notification_study_job", "notifications", type_="foreignkey")
    op.drop_column("notifications", "study_job_id")
    op.drop_table("study_jobs")
