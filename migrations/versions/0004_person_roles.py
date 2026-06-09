from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0004_person_roles"
down_revision = "0003_properties_gin_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "person",
        sa.Column("roles", sa.JSON(), nullable=False, server_default='["admin"]'),
    )


def downgrade() -> None:
    op.drop_column("person", "roles")
