"""Separate answer, draft and background embedding accounting."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_trace_operations"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("request_traces", "user_id", existing_type=postgresql.UUID(), nullable=True)
    op.add_column(
        "request_traces", sa.Column("operation", sa.String(32), nullable=False, server_default="question")
    )


def downgrade():
    op.execute("DELETE FROM request_traces WHERE user_id IS NULL")
    op.drop_column("request_traces", "operation")
    op.alter_column("request_traces", "user_id", existing_type=postgresql.UUID(), nullable=False)
