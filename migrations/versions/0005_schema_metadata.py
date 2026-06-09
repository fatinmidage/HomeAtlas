from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0005_schema_metadata"
down_revision = "0004_person_roles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "schema_metadata",
        sa.Column("key", sa.String(), primary_key=True),
        sa.Column("value", sa.String(), nullable=False),
    )
    op.execute("INSERT INTO schema_metadata (key, value) VALUES ('ontology_schema_version', '1')")


def downgrade() -> None:
    op.drop_table("schema_metadata")
