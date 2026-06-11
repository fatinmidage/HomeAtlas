from __future__ import annotations

from alembic import op

revision = "0003_properties_gin_index"
down_revision = "0002_event_version"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("ALTER TABLE item ALTER COLUMN properties TYPE jsonb USING properties::jsonb")
    op.execute("ALTER TABLE event ALTER COLUMN before TYPE jsonb USING before::jsonb")
    op.execute('ALTER TABLE event ALTER COLUMN "after" TYPE jsonb USING "after"::jsonb')
    op.execute("CREATE INDEX ix_item_properties_gin ON item USING gin (properties jsonb_path_ops)")


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("DROP INDEX IF EXISTS ix_item_properties_gin")
    op.execute("ALTER TABLE item ALTER COLUMN properties TYPE json USING properties::json")
    op.execute("ALTER TABLE event ALTER COLUMN before TYPE json USING before::json")
    op.execute('ALTER TABLE event ALTER COLUMN "after" TYPE json USING "after"::json')
