"""Persist practice answers and grading."""

import sqlalchemy as sa
from alembic import op

revision = "0009_practice_grading"
down_revision = "0008_material_granularity"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("study_runs", sa.Column("grading", sa.JSON(), nullable=False, server_default="{}"))


def downgrade():
    op.drop_column("study_runs", "grading")
