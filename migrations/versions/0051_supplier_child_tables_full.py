"""supplier child tables full

Revision ID: 0051_supplier_child_tables_full
Revises: 0050_supplier_status_and_child
Create Date: 2026-10-13

Tambah 4 tabel anak Supplier supaya setara dengan Customer:
    - supplier_addresses        : multiple alamat (billing/shipping)
    - supplier_contacts         : multiple PIC
    - supplier_tags             : label/kategori bebas
    - supplier_credit_history   : audit trail perubahan credit_limit
    - supplier_balance_history  : audit trail perubahan AP balance
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PGUUID


# revision identifiers, used by Alembic.
revision = "0051_supplier_child_tables_full"
down_revision = "0050_supplier_status_and_child"
branch_labels = None
depends_on = None


def _base_columns() -> list[sa.Column]:
    """Kolom created_at/updated_at standar untuk semua tabel anak."""
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    ]


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. supplier_addresses
    # ------------------------------------------------------------------
    op.create_table(
        "supplier_addresses",
        sa.Column("id", PGUUID(as_uuid=True), primary_key=True),
        sa.Column(
            "supplier_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("supplier.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "address_type", sa.String(20), nullable=False, server_default="other"
        ),
        sa.Column("label", sa.String(100), nullable=True),
        sa.Column("address_line", sa.Text(), nullable=False),
        sa.Column("city", sa.String(100), nullable=True),
        sa.Column("province", sa.String(100), nullable=True),
        sa.Column("district", sa.String(100), nullable=True),
        sa.Column("postal_code", sa.String(20), nullable=True),
        sa.Column("country", sa.String(2), nullable=False, server_default="ID"),
        sa.Column("latitude", sa.Numeric(10, 6), nullable=True),
        sa.Column("longitude", sa.Numeric(10, 6), nullable=True),
        sa.Column(
            "is_primary", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        *_base_columns(),
    )
    op.create_index(
        "idx_supplier_address_supplier_id", "supplier_addresses", ["supplier_id"]
    )
    op.create_index(
        "idx_supplier_address_type", "supplier_addresses", ["address_type"]
    )

    # ------------------------------------------------------------------
    # 2. supplier_contacts
    # ------------------------------------------------------------------
    op.create_table(
        "supplier_contacts",
        sa.Column("id", PGUUID(as_uuid=True), primary_key=True),
        sa.Column(
            "supplier_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("supplier.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("position", sa.String(100), nullable=True),
        sa.Column("phone", sa.String(20), nullable=True),
        sa.Column("mobile", sa.String(20), nullable=True),
        sa.Column("email", sa.String(200), nullable=True),
        sa.Column("whatsapp", sa.String(20), nullable=True),
        sa.Column(
            "is_primary", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        *_base_columns(),
    )
    op.create_index(
        "idx_supplier_contact_supplier_id", "supplier_contacts", ["supplier_id"]
    )

    # ------------------------------------------------------------------
    # 3. supplier_tags
    # ------------------------------------------------------------------
    op.create_table(
        "supplier_tags",
        sa.Column("id", PGUUID(as_uuid=True), primary_key=True),
        sa.Column(
            "supplier_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("supplier.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tag", sa.String(50), nullable=False),
        *_base_columns(),
    )
    op.create_unique_constraint(
        "uq_supplier_tag", "supplier_tags", ["supplier_id", "tag"]
    )
    op.create_index(
        "idx_supplier_tag_supplier_id", "supplier_tags", ["supplier_id"]
    )
    op.create_index("idx_supplier_tag_value", "supplier_tags", ["tag"])

    # ------------------------------------------------------------------
    # 4. supplier_credit_history (immutable audit trail)
    # ------------------------------------------------------------------
    op.create_table(
        "supplier_credit_history",
        sa.Column("id", PGUUID(as_uuid=True), primary_key=True),
        sa.Column(
            "supplier_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("supplier.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("old_limit", sa.Numeric(20, 2), nullable=False),
        sa.Column("new_limit", sa.Numeric(20, 2), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("changed_by", PGUUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "idx_supplier_credit_history_supplier_id",
        "supplier_credit_history",
        ["supplier_id"],
    )

    # ------------------------------------------------------------------
    # 5. supplier_balance_history (immutable audit trail)
    # ------------------------------------------------------------------
    op.create_table(
        "supplier_balance_history",
        sa.Column("id", PGUUID(as_uuid=True), primary_key=True),
        sa.Column(
            "supplier_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("supplier.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("old_balance", sa.Numeric(20, 2), nullable=False),
        sa.Column("new_balance", sa.Numeric(20, 2), nullable=False),
        sa.Column("delta", sa.Numeric(20, 2), nullable=False),
        sa.Column("source", sa.String(50), nullable=True),
        sa.Column("reference", sa.String(100), nullable=True),
        sa.Column("changed_by", PGUUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "idx_supplier_balance_history_supplier_id",
        "supplier_balance_history",
        ["supplier_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_supplier_balance_history_supplier_id",
        table_name="supplier_balance_history",
    )
    op.drop_table("supplier_balance_history")

    op.drop_index(
        "idx_supplier_credit_history_supplier_id",
        table_name="supplier_credit_history",
    )
    op.drop_table("supplier_credit_history")

    op.drop_index("idx_supplier_tag_value", table_name="supplier_tags")
    op.drop_index("idx_supplier_tag_supplier_id", table_name="supplier_tags")
    op.drop_constraint("uq_supplier_tag", "supplier_tags", type_="unique")
    op.drop_table("supplier_tags")

    op.drop_index(
        "idx_supplier_contact_supplier_id", table_name="supplier_contacts"
    )
    op.drop_table("supplier_contacts")

    op.drop_index("idx_supplier_address_type", table_name="supplier_addresses")
    op.drop_index(
        "idx_supplier_address_supplier_id", table_name="supplier_addresses"
    )
    op.drop_table("supplier_addresses")
    