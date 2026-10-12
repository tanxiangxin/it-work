"""Preserve provenance and website sources for study answers."""

import sqlalchemy as sa
from alembic import op

revision = "0006_study_web_sources"
down_revision = "0005_campus_learning"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "study_runs", sa.Column("answer_kind", sa.String(16), server_default="knowledge", nullable=False)
    )
    op.add_column("study_runs", sa.Column("web_sources", sa.JSON(), server_default="[]", nullable=False))


def downgrade():
    op.drop_column("study_runs", "web_sources")
    op.drop_column("study_runs", "answer_kind")
