from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0002_event_version"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("event", sa.Column("version", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("event", "version")
