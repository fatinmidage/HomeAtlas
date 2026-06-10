from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0007_event_item_version_unique"
down_revision = "0006_person_roles_member_default"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_event_item_version",
        "event",
        ["item_id", "version"],
        unique=True,
        postgresql_where=sa.text("item_id IS NOT NULL AND version IS NOT NULL"),
        sqlite_where=sa.text("item_id IS NOT NULL AND version IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_event_item_version", table_name="event")
