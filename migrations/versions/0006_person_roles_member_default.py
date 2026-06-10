from __future__ import annotations

from alembic import op

revision = "0006_person_roles_member_default"
down_revision = "0005_schema_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("person") as batch_op:
        batch_op.alter_column("roles", server_default='["member"]')


def downgrade() -> None:
    with op.batch_alter_table("person") as batch_op:
        batch_op.alter_column("roles", server_default='["admin"]')
