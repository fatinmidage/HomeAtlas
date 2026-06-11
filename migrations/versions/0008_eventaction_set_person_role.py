from __future__ import annotations

from alembic import op

revision = "0008_eventaction_set_person_role"
down_revision = "0007_event_item_version_unique"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("ALTER TYPE eventaction ADD VALUE IF NOT EXISTS 'SET_PERSON_ROLE'")


def downgrade() -> None:
    pass
