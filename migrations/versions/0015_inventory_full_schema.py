"""expand inventory_item to full ERP column set + new inventory master tables

Revision ID: 0015invfull
Revises: journal_header_fix_001
Create Date: 2026-08-07 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, NUMERIC, UUID

revision: str = "0015invfull"
down_revision = "journal_header_fix_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. TABEL MASTER BARU: uom, inventory_category
    # ------------------------------------------------------------------
    op.create_table(
        "uom",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("legal_entity_id", UUID(as_uuid=True), sa.ForeignKey("legal_entity.id"), nullable=False),
        sa.Column("uom_code", sa.String(10), nullable=False),
        sa.Column("uom_name", sa.String(50), nullable=False),
        sa.Column("uom_category", sa.String(30), nullable=True),
        sa.Column("is_base_uom", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("base_uom_id", UUID(as_uuid=True), sa.ForeignKey("uom.id", ondelete="SET NULL"), nullable=True),
        sa.Column("conversion_factor", NUMERIC(18, 6), nullable=False, server_default="1"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_by", UUID(as_uuid=True), nullable=True),
        sa.UniqueConstraint("uom_code", "legal_entity_id", name="uq_uom_code_legal_entity"),
    )
    op.create_index("idx_uom_code", "uom", ["uom_code"])
    op.create_index("idx_uom_legal_entity", "uom", ["legal_entity_id"])

    op.create_table(
        "inventory_category",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("legal_entity_id", UUID(as_uuid=True), sa.ForeignKey("legal_entity.id"), nullable=False),
        sa.Column("category_code", sa.String(30), nullable=False),
        sa.Column("category_name", sa.String(150), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column(
            "parent_id", UUID(as_uuid=True), sa.ForeignKey("inventory_category.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_by", UUID(as_uuid=True), nullable=True),
        sa.UniqueConstraint("category_code", "legal_entity_id", name="uq_inventory_category_code_legal_entity"),
    )
    op.create_index("idx_inv_category_code", "inventory_category", ["category_code"])
    op.create_index("idx_inv_category_parent", "inventory_category", ["parent_id"])
    op.create_index("idx_inv_category_legal_entity", "inventory_category", ["legal_entity_id"])

    # ------------------------------------------------------------------
    # 2. KOLOM BARU DI inventory_item (15 grup sesuai spesifikasi)
    # ------------------------------------------------------------------
    new_columns = [
        # 1. Identitas
        sa.Column("barcode", sa.String(64), nullable=True),
        sa.Column("sku", sa.String(64), nullable=True),
        sa.Column("part_number", sa.String(64), nullable=True),
        sa.Column("item_alias", sa.String(200), nullable=True),
        sa.Column("specification", sa.Text, nullable=True),
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column("serial_required", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("batch_required", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("qr_code", sa.String(128), nullable=True),
        # 2. Kategori
        sa.Column("category_id", UUID(as_uuid=True), nullable=True),
        sa.Column("subcategory_id", UUID(as_uuid=True), nullable=True),
        sa.Column("item_group", sa.String(50), nullable=True),
        sa.Column("inventory_type", sa.String(20), nullable=False, server_default="finished_goods"),
        # 3. UOM
        sa.Column("base_uom_id", UUID(as_uuid=True), nullable=True),
        sa.Column("purchase_uom_id", UUID(as_uuid=True), nullable=True),
        sa.Column("sales_uom_id", UUID(as_uuid=True), nullable=True),
        sa.Column("conversion_factor", NUMERIC(18, 6), nullable=False, server_default="1"),
        sa.Column("weight", NUMERIC(18, 4), nullable=True),
        sa.Column("length", NUMERIC(18, 4), nullable=True),
        sa.Column("width", NUMERIC(18, 4), nullable=True),
        sa.Column("height", NUMERIC(18, 4), nullable=True),
        sa.Column("volume", NUMERIC(18, 4), nullable=True),
        # 4. Harga
        sa.Column("cost_price", NUMERIC(20, 2), nullable=False, server_default="0"),
        sa.Column("minimum_selling_price", NUMERIC(20, 2), nullable=False, server_default="0"),
        sa.Column("wholesale_price", NUMERIC(20, 2), nullable=False, server_default="0"),
        sa.Column("retail_price", NUMERIC(20, 2), nullable=False, server_default="0"),
        sa.Column("discount_allowed", NUMERIC(5, 2), nullable=False, server_default="0"),
        # 5. Pajak
        sa.Column("purchase_tax_id", UUID(as_uuid=True), nullable=True),
        sa.Column("sales_tax_id", UUID(as_uuid=True), nullable=True),
        sa.Column("tax_included", sa.Boolean, nullable=False, server_default=sa.text("false")),
        # 6. Stock control
        sa.Column("reserved_stock", NUMERIC(20, 2), nullable=False, server_default="0"),
        sa.Column("available_stock", NUMERIC(20, 2), nullable=False, server_default="0"),
        sa.Column("incoming_stock", NUMERIC(20, 2), nullable=False, server_default="0"),
        sa.Column("outgoing_stock", NUMERIC(20, 2), nullable=False, server_default="0"),
        sa.Column("minimum_stock", NUMERIC(20, 2), nullable=True),
        sa.Column("maximum_stock", NUMERIC(20, 2), nullable=True),
        sa.Column("reorder_level", NUMERIC(20, 2), nullable=False, server_default="0"),
        sa.Column("reorder_qty", NUMERIC(20, 2), nullable=False, server_default="0"),
        sa.Column("safety_stock", NUMERIC(20, 2), nullable=False, server_default="0"),
        # 7. Warehouse
        sa.Column("default_bin", sa.String(30), nullable=True),
        sa.Column("rack", sa.String(30), nullable=True),
        sa.Column("shelf", sa.String(30), nullable=True),
        sa.Column("location", sa.String(100), nullable=True),
        # 8. Supplier
        sa.Column("default_supplier_id", UUID(as_uuid=True), nullable=True),
        sa.Column("supplier_item_code", sa.String(50), nullable=True),
        sa.Column("lead_time_days", sa.Integer, nullable=False, server_default="0"),
        sa.Column("minimum_order_qty", NUMERIC(20, 2), nullable=False, server_default="0"),
        # 9. Accounting
        sa.Column("inventory_account_id", UUID(as_uuid=True), nullable=True),
        sa.Column("cogs_account_id", UUID(as_uuid=True), nullable=True),
        sa.Column("sales_account_id", UUID(as_uuid=True), nullable=True),
        sa.Column("purchase_account_id", UUID(as_uuid=True), nullable=True),
        sa.Column("adjustment_account_id", UUID(as_uuid=True), nullable=True),
        sa.Column("inventory_method", sa.String(10), nullable=False, server_default="FIFO"),
        # 10. Manufacturing
        sa.Column("bom_required", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("bom_id", UUID(as_uuid=True), nullable=True),
        sa.Column("production_time", NUMERIC(10, 2), nullable=True),
        sa.Column("routing_id", UUID(as_uuid=True), nullable=True),
        # 11. Expired item
        sa.Column("expired_tracking", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("shelf_life_days", sa.Integer, nullable=True),
        sa.Column("manufacture_date", sa.Date, nullable=True),
        sa.Column("expired_date", sa.Date, nullable=True),
        # 12. Serial number
        sa.Column("serial_tracking", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("warranty_month", sa.Integer, nullable=True),
        sa.Column("asset_tracking", sa.Boolean, nullable=False, server_default=sa.text("false")),
        # 13. Gambar
        sa.Column("image_url", sa.Text, nullable=True),
        sa.Column("attachment_url", sa.Text, nullable=True),
        # 14. Status
        sa.Column("sellable", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("purchasable", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("stock_item", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("allow_negative_stock", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("remarks", sa.Text, nullable=True),
        # 15. Audit
        sa.Column("updated_by", UUID(as_uuid=True), nullable=True),
        sa.Column("deleted_by", UUID(as_uuid=True), nullable=True),
    ]
    for col in new_columns:
        op.add_column("inventory_item", col)

    # min_stock/max_stock/reorder_point/reorder_quantity sudah ada dari migration 0013 (dipertahankan sbg legacy alias)

    # ------------------------------------------------------------------
    # 3. FOREIGN KEYS untuk kolom relasi baru
    # ------------------------------------------------------------------
    op.create_foreign_key(
        "fk_inventory_item_category", "inventory_item", "inventory_category", ["category_id"], ["id"], ondelete="SET NULL"
    )
    op.create_foreign_key(
        "fk_inventory_item_subcategory", "inventory_item", "inventory_category", ["subcategory_id"], ["id"], ondelete="SET NULL"
    )
    op.create_foreign_key(
        "fk_inventory_item_base_uom", "inventory_item", "uom", ["base_uom_id"], ["id"], ondelete="SET NULL"
    )
    op.create_foreign_key(
        "fk_inventory_item_purchase_uom", "inventory_item", "uom", ["purchase_uom_id"], ["id"], ondelete="SET NULL"
    )
    op.create_foreign_key(
        "fk_inventory_item_sales_uom", "inventory_item", "uom", ["sales_uom_id"], ["id"], ondelete="SET NULL"
    )
    op.create_foreign_key(
        "fk_inventory_item_supplier", "inventory_item", "supplier", ["default_supplier_id"], ["id"], ondelete="SET NULL"
    )
    for col, fk_name in [
        ("inventory_account_id", "fk_inventory_item_inv_account"),
        ("cogs_account_id", "fk_inventory_item_cogs_account"),
        ("sales_account_id", "fk_inventory_item_sales_account"),
        ("purchase_account_id", "fk_inventory_item_purchase_account"),
        ("adjustment_account_id", "fk_inventory_item_adjustment_account"),
    ]:
        op.create_foreign_key(
            fk_name, "inventory_item", "account", [col], ["id"], ondelete="SET NULL"
        )

    # ------------------------------------------------------------------
    # 4. CHECK CONSTRAINTS baru + unique tambahan
    # ------------------------------------------------------------------
    op.create_check_constraint(
        "ck_inventory_item_inventory_type",
        "inventory_item",
        "inventory_type IN ('raw_material','finished_goods','semi_finished','service',"
        "'sparepart','consumable','asset','non_inventory')",
    )
    op.create_check_constraint(
        "ck_inventory_item_inventory_method",
        "inventory_item",
        "inventory_method IN ('FIFO','LIFO','AVERAGE','STANDARD')",
    )
    op.create_check_constraint(
        "ck_inventory_item_conversion_factor_pos", "inventory_item", "conversion_factor > 0"
    )
    op.create_check_constraint(
        "ck_inventory_item_min_order_qty_nonneg", "inventory_item", "minimum_order_qty >= 0"
    )
    op.create_unique_constraint("uq_inventory_item_sku_legal_entity", "inventory_item", ["sku", "legal_entity_id"])
    op.create_unique_constraint("uq_inventory_item_barcode", "inventory_item", ["barcode"])

    op.create_index("idx_inventory_item_sku", "inventory_item", ["sku"])
    op.create_index("idx_inventory_item_barcode", "inventory_item", ["barcode"])
    op.create_index("idx_inventory_item_inventory_type", "inventory_item", ["inventory_type"])
    op.create_index("idx_inventory_item_category", "inventory_item", ["category_id"])
    op.create_index("idx_inventory_item_supplier", "inventory_item", ["default_supplier_id"])
    op.create_index("idx_inventory_item_expired_date", "inventory_item", ["expired_date"])

    # ------------------------------------------------------------------
    # 5. Backfill: sinkronkan kolom baru dari kolom legacy agar data lama konsisten
    # ------------------------------------------------------------------
    op.execute("UPDATE inventory_item SET sku = item_code WHERE sku IS NULL")
    op.execute("UPDATE inventory_item SET available_stock = current_stock - reserved_stock")
    op.execute("UPDATE inventory_item SET inventory_method = valuation_method")
    op.execute("UPDATE inventory_item SET minimum_stock = min_stock, maximum_stock = max_stock")
    op.execute("UPDATE inventory_item SET reorder_level = reorder_point, reorder_qty = reorder_quantity")
    op.execute("UPDATE inventory_item SET cost_price = standard_cost")

    # ------------------------------------------------------------------
    # 6. TABEL BARU: batch, serial number, price history, image
    # ------------------------------------------------------------------
    op.create_table(
        "inventory_batch",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("legal_entity_id", UUID(as_uuid=True), sa.ForeignKey("legal_entity.id"), nullable=False),
        sa.Column("item_id", UUID(as_uuid=True), sa.ForeignKey("inventory_item.id", ondelete="CASCADE"), nullable=False),
        sa.Column("warehouse_id", UUID(as_uuid=True), sa.ForeignKey("warehouse.id", ondelete="SET NULL"), nullable=True),
        sa.Column("batch_number", sa.String(50), nullable=False),
        sa.Column("quantity", NUMERIC(20, 2), nullable=False, server_default="0"),
        sa.Column("unit_cost", NUMERIC(20, 2), nullable=False, server_default="0"),
        sa.Column("manufacture_date", sa.Date, nullable=True),
        sa.Column("expired_date", sa.Date, nullable=True),
        sa.Column("supplier_batch_ref", sa.String(50), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_by", UUID(as_uuid=True), nullable=True),
        sa.UniqueConstraint("item_id", "batch_number", "warehouse_id", name="uq_inventory_batch_item_number_wh"),
    )
    op.create_index("idx_inventory_batch_item", "inventory_batch", ["item_id"])
    op.create_index("idx_inventory_batch_number", "inventory_batch", ["batch_number"])
    op.create_index("idx_inventory_batch_expired_date", "inventory_batch", ["expired_date"])

    op.create_table(
        "inventory_serial_number",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("legal_entity_id", UUID(as_uuid=True), sa.ForeignKey("legal_entity.id"), nullable=False),
        sa.Column("item_id", UUID(as_uuid=True), sa.ForeignKey("inventory_item.id", ondelete="CASCADE"), nullable=False),
        sa.Column("warehouse_id", UUID(as_uuid=True), sa.ForeignKey("warehouse.id", ondelete="SET NULL"), nullable=True),
        sa.Column("serial_number", sa.String(100), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="in_stock"),
        sa.Column("warranty_start_date", sa.Date, nullable=True),
        sa.Column("warranty_end_date", sa.Date, nullable=True),
        sa.Column("customer_id", UUID(as_uuid=True), nullable=True),
        sa.Column("sold_at", sa.Date, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_by", UUID(as_uuid=True), nullable=True),
        sa.UniqueConstraint("item_id", "serial_number", name="uq_inventory_serial_item_number"),
        sa.CheckConstraint(
            "status IN ('in_stock','reserved','sold','returned','scrapped')",
            name="ck_inventory_serial_status",
        ),
    )
    op.create_index("idx_inventory_serial_item", "inventory_serial_number", ["item_id"])
    op.create_index("idx_inventory_serial_number", "inventory_serial_number", ["serial_number"])

    op.create_table(
        "inventory_price_history",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("legal_entity_id", UUID(as_uuid=True), sa.ForeignKey("legal_entity.id"), nullable=False),
        sa.Column("item_id", UUID(as_uuid=True), sa.ForeignKey("inventory_item.id", ondelete="CASCADE"), nullable=False),
        sa.Column("price_type", sa.String(30), nullable=False),
        sa.Column("old_price", NUMERIC(20, 2), nullable=False, server_default="0"),
        sa.Column("new_price", NUMERIC(20, 2), nullable=False, server_default="0"),
        sa.Column("effective_date", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("reason", sa.String(255), nullable=True),
        sa.Column("changed_by", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "price_type IN ('cost_price','standard_cost','average_cost','last_cost',"
            "'selling_price','minimum_selling_price','wholesale_price','retail_price')",
            name="ck_inventory_price_history_type",
        ),
    )
    op.create_index("idx_inventory_price_history_item", "inventory_price_history", ["item_id"])
    op.create_index("idx_inventory_price_history_effective", "inventory_price_history", ["effective_date"])

    op.create_table(
        "inventory_image",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("legal_entity_id", UUID(as_uuid=True), sa.ForeignKey("legal_entity.id"), nullable=False),
        sa.Column("item_id", UUID(as_uuid=True), sa.ForeignKey("inventory_item.id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_url", sa.Text, nullable=False),
        sa.Column("file_type", sa.String(20), nullable=False, server_default="image"),
        sa.Column("file_name", sa.String(255), nullable=True),
        sa.Column("is_primary", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_by", UUID(as_uuid=True), nullable=True),
    )
    op.create_index("idx_inventory_image_item", "inventory_image", ["item_id"])


def downgrade() -> None:
    op.drop_table("inventory_image")
    op.drop_table("inventory_price_history")
    op.drop_table("inventory_serial_number")
    op.drop_table("inventory_batch")

    op.drop_constraint("uq_inventory_item_barcode", "inventory_item", type_="unique")
    op.drop_constraint("uq_inventory_item_sku_legal_entity", "inventory_item", type_="unique")
    op.drop_constraint("ck_inventory_item_min_order_qty_nonneg", "inventory_item", type_="check")
    op.drop_constraint("ck_inventory_item_conversion_factor_pos", "inventory_item", type_="check")
    op.drop_constraint("ck_inventory_item_inventory_method", "inventory_item", type_="check")
    op.drop_constraint("ck_inventory_item_inventory_type", "inventory_item", type_="check")

    for fk_name in [
        "fk_inventory_item_adjustment_account",
        "fk_inventory_item_purchase_account",
        "fk_inventory_item_sales_account",
        "fk_inventory_item_cogs_account",
        "fk_inventory_item_inv_account",
        "fk_inventory_item_supplier",
        "fk_inventory_item_sales_uom",
        "fk_inventory_item_purchase_uom",
        "fk_inventory_item_base_uom",
        "fk_inventory_item_subcategory",
        "fk_inventory_item_category",
    ]:
        op.drop_constraint(fk_name, "inventory_item", type_="foreignkey")

    drop_cols = [
        "barcode", "sku", "part_number", "item_alias", "specification", "model",
        "serial_required", "batch_required", "qr_code",
        "category_id", "subcategory_id", "item_group", "inventory_type",
        "base_uom_id", "purchase_uom_id", "sales_uom_id", "conversion_factor",
        "weight", "length", "width", "height", "volume",
        "cost_price", "minimum_selling_price", "wholesale_price", "retail_price", "discount_allowed",
        "purchase_tax_id", "sales_tax_id", "tax_included",
        "reserved_stock", "available_stock", "incoming_stock", "outgoing_stock",
        "minimum_stock", "maximum_stock", "reorder_level", "reorder_qty", "safety_stock",
        "default_bin", "rack", "shelf", "location",
        "default_supplier_id", "supplier_item_code", "lead_time_days", "minimum_order_qty",
        "inventory_account_id", "cogs_account_id", "sales_account_id", "purchase_account_id",
        "adjustment_account_id", "inventory_method",
        "bom_required", "bom_id", "production_time", "routing_id",
        "expired_tracking", "shelf_life_days", "manufacture_date", "expired_date",
        "serial_tracking", "warranty_month", "asset_tracking",
        "image_url", "attachment_url",
        "sellable", "purchasable", "stock_item", "allow_negative_stock", "remarks",
        "updated_by", "deleted_by",
    ]
    for col in drop_cols:
        op.drop_column("inventory_item", col)

    op.drop_table("inventory_category")
    op.drop_table("uom")
