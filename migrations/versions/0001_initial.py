from __future__ import annotations

from alembic import op
import sqlalchemy as sa
import sqlmodel

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "person",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index(op.f("ix_person_name"), "person", ["name"], unique=False)
    op.create_table(
        "location",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.Column("notes", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["parent_id"], ["location.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index(op.f("ix_location_name"), "location", ["name"], unique=False)
    op.create_table(
        "item",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("kind", sa.Enum("FOOD", "MEDICINE", "INSURANCE_POLICY", "PAYMENT_CARD", "MEMBERSHIP_CARD", "DOCUMENT", "TOOL", "APPLIANCE", "OTHER", name="itemkind"), nullable=False),
        sa.Column("domain", sa.Enum("PERISHABLE", "CARDS_DOCS", "EQUIPMENT", "OTHER", name="itemdomain"), nullable=False),
        sa.Column("location_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=True),
        sa.Column("unit", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("renewal_date", sa.Date(), nullable=True),
        sa.Column("purchase_date", sa.Date(), nullable=True),
        sa.Column("properties", sa.JSON(), nullable=False),
        sa.Column("notes", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("added_by_id", sa.Integer(), nullable=False),
        sa.Column("updated_by_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["added_by_id"], ["person.id"]),
        sa.ForeignKeyConstraint(["location_id"], ["location.id"]),
        sa.ForeignKeyConstraint(["updated_by_id"], ["person.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_item_archived"), "item", ["archived"], unique=False)
    op.create_index(op.f("ix_item_domain"), "item", ["domain"], unique=False)
    op.create_index(op.f("ix_item_expiry_date"), "item", ["expiry_date"], unique=False)
    op.create_index(op.f("ix_item_kind"), "item", ["kind"], unique=False)
    op.create_index(op.f("ix_item_location_id"), "item", ["location_id"], unique=False)
    op.create_index(op.f("ix_item_name"), "item", ["name"], unique=False)
    op.create_index(op.f("ix_item_renewal_date"), "item", ["renewal_date"], unique=False)
    op.create_table(
        "event",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=True),
        sa.Column("actor_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.Enum("ADD_ITEM", "MOVE_ITEM", "ADJUST_QUANTITY", "SET_QUANTITY", "UPDATE_ITEM", "UPSERT_CARD_REFERENCE", "DISCARD_ITEM", name="eventaction"), nullable=False),
        sa.Column("summary", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("before", sa.JSON(), nullable=True),
        sa.Column("after", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["person.id"]),
        sa.ForeignKeyConstraint(["item_id"], ["item.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_event_action"), "event", ["action"], unique=False)
    op.create_index(op.f("ix_event_actor_id"), "event", ["actor_id"], unique=False)
    op.create_index(op.f("ix_event_created_at"), "event", ["created_at"], unique=False)
    op.create_index(op.f("ix_event_item_id"), "event", ["item_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_event_item_id"), table_name="event")
    op.drop_index(op.f("ix_event_created_at"), table_name="event")
    op.drop_index(op.f("ix_event_actor_id"), table_name="event")
    op.drop_index(op.f("ix_event_action"), table_name="event")
    op.drop_table("event")
    op.drop_index(op.f("ix_item_renewal_date"), table_name="item")
    op.drop_index(op.f("ix_item_name"), table_name="item")
    op.drop_index(op.f("ix_item_location_id"), table_name="item")
    op.drop_index(op.f("ix_item_kind"), table_name="item")
    op.drop_index(op.f("ix_item_expiry_date"), table_name="item")
    op.drop_index(op.f("ix_item_domain"), table_name="item")
    op.drop_index(op.f("ix_item_archived"), table_name="item")
    op.drop_table("item")
    op.drop_index(op.f("ix_location_name"), table_name="location")
    op.drop_table("location")
    op.drop_index(op.f("ix_person_name"), table_name="person")
    op.drop_table("person")

