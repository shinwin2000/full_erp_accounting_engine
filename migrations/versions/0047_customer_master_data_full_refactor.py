"""customer master data full refactor - address/contact/attachment/note/tag/history tables

Revision ID: 0047
Revises: journal_header_fix_001
Create Date: 2026-08-07 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, NUMERIC, UUID

revision: str = "0047"
down_revision: Union[str, None] = "journal_header_fix_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Kolom baru di tabel customer (data utama, alamat, finance, status)
    # ------------------------------------------------------------------
    op.add_column("customer", sa.Column("company_name", sa.String(200), nullable=True))
    op.add_column("customer", sa.Column("is_taxable", sa.Boolean, nullable=False, server_default="true"))
    op.add_column("customer", sa.Column("province", sa.String(100), nullable=True))
    op.add_column("customer", sa.Column("district", sa.String(100), nullable=True))
    op.add_column("customer", sa.Column("latitude", NUMERIC(10, 6), nullable=True))
    op.add_column("customer", sa.Column("longitude", NUMERIC(10, 6), nullable=True))
    op.add_column("customer", sa.Column("mobile", sa.String(20), nullable=True))
    op.add_column("customer", sa.Column("opening_balance", NUMERIC(20, 2), nullable=False, server_default="0"))
    op.add_column("customer", sa.Column("current_balance", NUMERIC(20, 2), nullable=False, server_default="0"))
    op.add_column("customer", sa.Column("currency", sa.String(3), nullable=False, server_default="IDR"))
    op.add_column("customer", sa.Column("is_blacklist", sa.Boolean, nullable=False, server_default="false"))
    op.add_column("customer", sa.Column("updated_by", UUID(as_uuid=True), nullable=True))

    # ------------------------------------------------------------------
    # 2. customer_addresses
    # ------------------------------------------------------------------
    op.create_table(
        "customer_addresses",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("customer_id", UUID(as_uuid=True), nullable=False),
        sa.Column("address_type", sa.String(20), nullable=False, server_default="other"),
        sa.Column("label", sa.String(100), nullable=True),
        sa.Column("address_line", sa.Text, nullable=False),
        sa.Column("city", sa.String(100), nullable=True),
        sa.Column("province", sa.String(100), nullable=True),
        sa.Column("district", sa.String(100), nullable=True),
        sa.Column("postal_code", sa.String(20), nullable=True),
        sa.Column("country", sa.String(2), nullable=False, server_default="ID"),
        sa.Column("latitude", NUMERIC(10, 6), nullable=True),
        sa.Column("longitude", NUMERIC(10, 6), nullable=True),
        sa.Column("is_primary", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_customer_address_customer_id", "customer_addresses", ["customer_id"])
    op.create_index("idx_customer_address_type", "customer_addresses", ["address_type"])
    op.create_foreign_key(
        "fk_customer_address_customer", "customer_addresses", "customer",
        ["customer_id"], ["id"], ondelete="CASCADE",
    )
    op.create_check_constraint(
        "ck_customer_address_type", "customer_addresses",
        "address_type IN ('billing', 'shipping', 'warehouse', 'other')",
    )

    # ------------------------------------------------------------------
    # 3. customer_contacts
    # ------------------------------------------------------------------
    op.create_table(
        "customer_contacts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("customer_id", UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("position", sa.String(100), nullable=True),
        sa.Column("phone", sa.String(20), nullable=True),
        sa.Column("mobile", sa.String(20), nullable=True),
        sa.Column("email", sa.String(200), nullable=True),
        sa.Column("whatsapp", sa.String(20), nullable=True),
        sa.Column("is_primary", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_customer_contact_customer_id", "customer_contacts", ["customer_id"])
    op.create_foreign_key(
        "fk_customer_contact_customer", "customer_contacts", "customer",
        ["customer_id"], ["id"], ondelete="CASCADE",
    )

    # ------------------------------------------------------------------
    # 4. customer_attachments
    # ------------------------------------------------------------------
    op.create_table(
        "customer_attachments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("customer_id", UUID(as_uuid=True), nullable=False),
        sa.Column("document_type", sa.String(30), nullable=False, server_default="other"),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("file_path", sa.Text, nullable=False),
        sa.Column("file_size_bytes", sa.Integer, nullable=True),
        sa.Column("mime_type", sa.String(100), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("uploaded_by", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_customer_attachment_customer_id", "customer_attachments", ["customer_id"])
    op.create_foreign_key(
        "fk_customer_attachment_customer", "customer_attachments", "customer",
        ["customer_id"], ["id"], ondelete="CASCADE",
    )

    # ------------------------------------------------------------------
    # 5. customer_notes
    # ------------------------------------------------------------------
    op.create_table(
        "customer_notes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("customer_id", UUID(as_uuid=True), nullable=False),
        sa.Column("note", sa.Text, nullable=False),
        sa.Column("created_by", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_customer_note_customer_id", "customer_notes", ["customer_id"])
    op.create_foreign_key(
        "fk_customer_note_customer", "customer_notes", "customer",
        ["customer_id"], ["id"], ondelete="CASCADE",
    )

    # ------------------------------------------------------------------
    # 6. customer_tags
    # ------------------------------------------------------------------
    op.create_table(
        "customer_tags",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("customer_id", UUID(as_uuid=True), nullable=False),
        sa.Column("tag", sa.String(50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_customer_tag_customer_id", "customer_tags", ["customer_id"])
    op.create_index("idx_customer_tag_value", "customer_tags", ["tag"])
    op.create_unique_constraint("uq_customer_tag", "customer_tags", ["customer_id", "tag"])
    op.create_foreign_key(
        "fk_customer_tag_customer", "customer_tags", "customer",
        ["customer_id"], ["id"], ondelete="CASCADE",
    )

    # ------------------------------------------------------------------
    # 7. customer_credit_history
    # ------------------------------------------------------------------
    op.create_table(
        "customer_credit_history",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("customer_id", UUID(as_uuid=True), nullable=False),
        sa.Column("old_limit", NUMERIC(20, 2), nullable=False),
        sa.Column("new_limit", NUMERIC(20, 2), nullable=False),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("changed_by", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_customer_credit_history_customer_id", "customer_credit_history", ["customer_id"])
    op.create_foreign_key(
        "fk_customer_credit_history_customer", "customer_credit_history", "customer",
        ["customer_id"], ["id"], ondelete="CASCADE",
    )

    # ------------------------------------------------------------------
    # 8. customer_balance_history
    # ------------------------------------------------------------------
    op.create_table(
        "customer_balance_history",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("customer_id", UUID(as_uuid=True), nullable=False),
        sa.Column("old_balance", NUMERIC(20, 2), nullable=False),
        sa.Column("new_balance", NUMERIC(20, 2), nullable=False),
        sa.Column("delta", NUMERIC(20, 2), nullable=False),
        sa.Column("source", sa.String(50), nullable=True),
        sa.Column("reference", sa.String(100), nullable=True),
        sa.Column("changed_by", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_customer_balance_history_customer_id", "customer_balance_history", ["customer_id"])
    op.create_foreign_key(
        "fk_customer_balance_history_customer", "customer_balance_history", "customer",
        ["customer_id"], ["id"], ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_table("customer_balance_history")
    op.drop_table("customer_credit_history")
    op.drop_table("customer_tags")
    op.drop_table("customer_notes")
    op.drop_table("customer_attachments")
    op.drop_table("customer_contacts")
    op.drop_table("customer_addresses")

    op.drop_column("customer", "updated_by")
    op.drop_column("customer", "is_blacklist")
    op.drop_column("customer", "currency")
    op.drop_column("customer", "current_balance")
    op.drop_column("customer", "opening_balance")
    op.drop_column("customer", "mobile")
    op.drop_column("customer", "longitude")
    op.drop_column("customer", "latitude")
    op.drop_column("customer", "district")
    op.drop_column("customer", "province")
    op.drop_column("customer", "is_taxable")
    op.drop_column("customer", "company_name")
