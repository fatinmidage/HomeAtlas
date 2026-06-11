from __future__ import annotations

from alembic import op

revision = "0009_timezone_aware_timestamps"
down_revision = "0008_eventaction_set_person_role"
branch_labels = None
depends_on = None

_COLUMNS = (
    ("person", "created_at"),
    ("location", "created_at"),
    ("item", "created_at"),
    ("item", "updated_at"),
    ("event", "created_at"),
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for table, column in _COLUMNS:
            op.execute(
                f'ALTER TABLE "{table}" ALTER COLUMN "{column}" '
                f'TYPE timestamptz USING "{column}" AT TIME ZONE \'UTC\''
            )
    op.execute("UPDATE schema_metadata SET value = '2' WHERE key = 'ontology_schema_version'")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for table, column in _COLUMNS:
            op.execute(
                f'ALTER TABLE "{table}" ALTER COLUMN "{column}" '
                f'TYPE timestamp USING "{column}" AT TIME ZONE \'UTC\''
            )
    op.execute("UPDATE schema_metadata SET value = '1' WHERE key = 'ontology_schema_version'")
