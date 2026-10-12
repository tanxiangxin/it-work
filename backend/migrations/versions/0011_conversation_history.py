"""Separate recent conversations from visible question and answer history."""

import sqlalchemy as sa
from alembic import op

revision = "0011_conversation_history"
down_revision = "0010_ai_configuration"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "conversations", sa.Column("recent_hidden", sa.Boolean(), server_default=sa.false(), nullable=False)
    )
    op.add_column(
        "conversations", sa.Column("history_hidden", sa.Boolean(), server_default=sa.false(), nullable=False)
    )


def downgrade():
    op.drop_column("conversations", "history_hidden")
    op.drop_column("conversations", "recent_hidden")
