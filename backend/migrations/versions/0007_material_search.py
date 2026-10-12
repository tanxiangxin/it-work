"""Background online course material generation."""

import sqlalchemy as sa
from alembic import op

revision = "0007_material_search"
down_revision = "0006_study_web_sources"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "material_searches",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("course_id", sa.Uuid(), sa.ForeignKey("courses.id"), nullable=False),
        sa.Column("topic", sa.String(300), nullable=False),
        sa.Column("limit", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("lease_token", sa.String(36)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("document_ids", sa.JSON(), nullable=False),
        sa.Column("job_ids", sa.JSON(), nullable=False),
        sa.CheckConstraint('"limit" BETWEEN 1 AND 10', name="material_search_limit"),
    )
    op.create_index("ix_material_searches_course_id", "material_searches", ["course_id"])
    op.create_index("ix_material_searches_user_id", "material_searches", ["user_id"])


def downgrade():
    op.drop_table("material_searches")
