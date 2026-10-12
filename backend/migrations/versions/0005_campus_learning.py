"""Campus notices, personal tasks and isolated course materials."""

import sqlalchemy as sa
from alembic import op

revision = "0005_campus_learning"
down_revision = "0004_notifications"
branch_labels = None
depends_on = None


def common():
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    ]


def fk(name, table, nullable=False):
    return sa.Column(name, sa.Uuid(), sa.ForeignKey(table + ".id"), nullable=nullable)


def upgrade():
    op.create_table(
        "announcements",
        *common(),
        fk("author_id", "users"),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("category", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("audience", sa.String(300), nullable=False),
        sa.Column("location", sa.String(300), nullable=False),
        sa.Column("deadline", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "subscriptions",
        *common(),
        fk("user_id", "users"),
        sa.Column("category", sa.String(16), nullable=False),
        sa.UniqueConstraint("user_id", "category"),
    )
    op.create_index("ix_subscriptions_user_id", "subscriptions", ["user_id"])
    op.create_table(
        "saved_announcements",
        *common(),
        fk("user_id", "users"),
        fk("announcement_id", "announcements"),
        sa.UniqueConstraint("user_id", "announcement_id"),
    )
    op.create_index("ix_saved_announcements_user_id", "saved_announcements", ["user_id"])
    op.create_table(
        "todos",
        *common(),
        fk("user_id", "users"),
        fk("announcement_id", "announcements", True),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True)),
        sa.Column("remind_at", sa.DateTime(timezone=True)),
        sa.Column("completed", sa.Boolean(), nullable=False),
        sa.Column("reminded_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("user_id", "announcement_id"),
    )
    op.create_index("ix_todos_user_id", "todos", ["user_id"])
    op.create_table(
        "courses", *common(), fk("user_id", "users"), sa.Column("name", sa.String(120), nullable=False)
    )
    op.create_index("ix_courses_user_id", "courses", ["user_id"])
    op.create_table(
        "study_runs",
        *common(),
        fk("user_id", "users"),
        fk("course_id", "courses"),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("citations", sa.JSON(), nullable=False),
        sa.Column("exercises", sa.JSON(), nullable=False),
        sa.Column("answerable", sa.Boolean(), nullable=False),
        sa.Column("model_mode", sa.String(16), nullable=False),
    )
    op.create_index("ix_study_runs_user_id", "study_runs", ["user_id"])
    op.create_index("ix_study_runs_course_id", "study_runs", ["course_id"])
    op.add_column("documents", fk("owner_id", "users", True))
    op.add_column("documents", fk("course_id", "courses", True))
    op.create_index("ix_documents_owner_id", "documents", ["owner_id"])
    op.create_index("ix_documents_course_id", "documents", ["course_id"])
    op.alter_column("notifications", "ticket_id", nullable=True)
    op.add_column("notifications", fk("announcement_id", "announcements", True))
    op.add_column("notifications", fk("todo_id", "todos", True))


def downgrade():
    op.drop_column("notifications", "todo_id")
    op.drop_column("notifications", "announcement_id")
    op.execute("DELETE FROM notifications WHERE ticket_id IS NULL")
    op.alter_column("notifications", "ticket_id", nullable=False)
    op.drop_column("documents", "course_id")
    op.drop_column("documents", "owner_id")
    for table in ["study_runs", "courses", "todos", "saved_announcements", "subscriptions", "announcements"]:
        op.drop_table(table)
