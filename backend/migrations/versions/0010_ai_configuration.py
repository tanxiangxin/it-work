"""Per-account chat model configuration."""

import sqlalchemy as sa
from alembic import op

revision = "0010_ai_configuration"
down_revision = "0009_practice_grading"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ai_configurations",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("api_base", sa.String(2048), nullable=False),
        sa.Column("model", sa.String(200), nullable=False),
        sa.Column("api_key", sa.Text(), nullable=False),
        sa.Column("api_style", sa.String(16), nullable=False),
    )


def downgrade():
    op.drop_table("ai_configurations")
