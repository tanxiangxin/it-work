"""Semantic chunks and reversible course material organization."""

import sqlalchemy as sa
from alembic import op

revision = "0008_material_granularity"
down_revision = "0007_material_search"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("documents", sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column(
        "document_versions",
        sa.Column("chunk_policy", sa.String(64), nullable=False, server_default="legacy-v1"),
    )
    # The original constraint was unnamed in the ORM; locate its database-assigned name.
    constraints = sa.inspect(op.get_bind()).get_unique_constraints("document_versions")
    for constraint in constraints:
        if set(constraint["column_names"]) == {"document_id", "file_hash", "index_key"}:
            op.drop_constraint(constraint["name"], "document_versions", type_="unique")
    op.create_unique_constraint(
        "uq_version_policy", "document_versions", ["document_id", "file_hash", "index_key", "chunk_policy"]
    )
    op.add_column("chunks", sa.Column("source_spans", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column(
        "material_searches",
        sa.Column("generation_done", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column("material_searches", sa.Column("timings", sa.JSON(), nullable=False, server_default="{}"))
    op.create_table(
        "material_organizations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("course_id", sa.Uuid(), sa.ForeignKey("courses.id"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        *[
            sa.Column(name, sa.JSON(), nullable=False)
            for name in ["groups", "old_document_ids", "new_document_ids", "job_ids"]
        ],
    )
    op.create_index("ix_material_organizations_course_id", "material_organizations", ["course_id"])
    op.create_index("ix_material_organizations_user_id", "material_organizations", ["user_id"])


def downgrade():
    duplicates = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT 1 FROM document_versions GROUP BY document_id, file_hash, index_key HAVING count(*) > 1 LIMIT 1"
            )
        )
        .first()
    )
    if duplicates:
        raise RuntimeError(
            "Cannot downgrade safely while multiple chunk-policy versions exist; restore the prior database backup."
        )
    op.drop_table("material_organizations")
    op.drop_column("material_searches", "timings")
    op.drop_column("material_searches", "generation_done")
    op.drop_column("chunks", "source_spans")
    op.drop_constraint("uq_version_policy", "document_versions", type_="unique")
    op.create_unique_constraint(
        "uq_version_legacy", "document_versions", ["document_id", "file_hash", "index_key"]
    )
    op.drop_column("document_versions", "chunk_policy")
    op.drop_column("documents", "archived")
