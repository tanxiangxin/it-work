"""Persist whether a reply uses knowledge sources or general conversation."""

import sqlalchemy as sa
from alembic import op

revision = "0003_message_answer_kind"
down_revision = "0002_trace_operations"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "messages", sa.Column("answer_kind", sa.String(16), nullable=False, server_default="knowledge")
    )


def downgrade():
    op.drop_column("messages", "answer_kind")
