"""
migrations/env.py
~~~~~~~~~~~~~~~~~
Alembic environment configuration - safe for both CLI and import.
"""

from __future__ import annotations
import importlib
import asyncio
import os
import sys
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# Alembic imports
from alembic import context

# Add project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ============================================================================
# METADATA LOADING (safe, done at module level)
# ============================================================================
target_metadata = None

try:
    from infrastructure.persistence_orm.base_model import Base
    target_metadata = Base.metadata
    print("[OK] Loaded Base metadata from infrastructure.persistence_orm.base_model")
except ImportError as e:
    print(f"[WARNING] Could not import Base metadata: {e}")

# Register all table models if metadata available
if target_metadata is not None:
    orm_modules = [
        "infrastructure.persistence_orm.account_table",
        "infrastructure.persistence_orm.amortization_schedule_table",
        "infrastructure.persistence_orm.ap_credit_note_table",
        "infrastructure.persistence_orm.ap_invoice_line_table",
        "infrastructure.persistence_orm.ap_invoice_table",
        "infrastructure.persistence_orm.ap_payment_table",
        "infrastructure.persistence_orm.ar_credit_note_table",
        "infrastructure.persistence_orm.ar_invoice_line_table",
        "infrastructure.persistence_orm.ar_invoice_table",
        "infrastructure.persistence_orm.ar_payment_table",
        "infrastructure.persistence_orm.asset_category_table",
        "infrastructure.persistence_orm.audit_event_table",
        "infrastructure.persistence_orm.bank_account_table",
        "infrastructure.persistence_orm.bank_reconciliation_table",
        "infrastructure.persistence_orm.bank_transaction_table",
        "infrastructure.persistence_orm.bill_of_materials_table",
        "infrastructure.persistence_orm.cash_book_table",
        "infrastructure.persistence_orm.consolidation_group_member_table",
        "infrastructure.persistence_orm.consolidation_group_table",
        "infrastructure.persistence_orm.coretax_bupot_table",
        "infrastructure.persistence_orm.coretax_emeterai_table",
        "infrastructure.persistence_orm.coretax_faktur_line_table",
        "infrastructure.persistence_orm.coretax_faktur_table",
        "infrastructure.persistence_orm.coretax_nsfp_table",
        "infrastructure.persistence_orm.coretax_ntpn_table",
        "infrastructure.persistence_orm.coretax_spt_table",
        "infrastructure.persistence_orm.cost_card_table",
        "infrastructure.persistence_orm.customer_table",
        "infrastructure.persistence_orm.dead_letter_table",
        "infrastructure.persistence_orm.depreciation_schedule_table",
        "infrastructure.persistence_orm.disposal_table",
        "infrastructure.persistence_orm.employee_table",
        "infrastructure.persistence_orm.event_store_table",
        "infrastructure.persistence_orm.fiscal_period_table",
        "infrastructure.persistence_orm.fixed_asset_table",
        "infrastructure.persistence_orm.goods_receipt_note_table",
        "infrastructure.persistence_orm.hash_chain_table",
        "infrastructure.persistence_orm.iam_user_table",
        "infrastructure.persistence_orm.impairment_test_table",
        "infrastructure.persistence_orm.intangible_asset_table",
        "infrastructure.persistence_orm.inventory_fifo_layer_table",
        "infrastructure.persistence_orm.inventory_item_table",
        "infrastructure.persistence_orm.inventory_movement_table",
        "infrastructure.persistence_orm.journal_header_table",
        "infrastructure.persistence_orm.journal_line_table",
        "infrastructure.persistence_orm.ledger_entry_table",
        "infrastructure.persistence_orm.legal_entity_branch_table",
        "infrastructure.persistence_orm.legal_entity_table",
        "infrastructure.persistence_orm.login_attempt_table",
        "infrastructure.persistence_orm.outbox_checkpoint_table",
        "infrastructure.persistence_orm.outbox_table",
        "infrastructure.persistence_orm.payroll_run_table",
        "infrastructure.persistence_orm.petty_cash_fund_table",
        "infrastructure.persistence_orm.projection_checkpoint_table",
        "infrastructure.persistence_orm.project_table",
        "infrastructure.persistence_orm.purchase_order_table",
        "infrastructure.persistence_orm.retainer_contract_table",
        "infrastructure.persistence_orm.revaluation_table",
        "infrastructure.persistence_orm.saga_state_table",
        "infrastructure.persistence_orm.salary_component_table",
        "infrastructure.persistence_orm.sales_order_table",
        "infrastructure.persistence_orm.stock_opname_table",
        "infrastructure.persistence_orm.supplier_table",
        "infrastructure.persistence_orm.system_setting_table",
        "infrastructure.persistence_orm.tax_transaction_table",
        "infrastructure.persistence_orm.time_entry_table",
        "infrastructure.persistence_orm.warehouse_table",
        "infrastructure.persistence_orm.work_order_table",
    ]
    for mod in orm_modules:
        try:
            importlib.import_module(mod)
        except ImportError:
            pass


# ============================================================================
# MIGRATION FUNCTIONS (called by Alembic)
# ============================================================================

def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    config = context.config
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Run migrations with a given connection."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run async migrations."""
    config = context.config
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


# ============================================================================
# MAIN ENTRY POINT - only executed when Alembic calls this script
# ============================================================================

# Alembic sets 'context' environment only when running migrations.
# We check if context has the required attributes before proceeding.
if hasattr(context, 'config') and context.config is not None:
    # Override database URL from environment if needed
    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        context.config.set_main_option("sqlalchemy.url", db_url)
    
    # Configure logging if alembic.ini has loggers
    if context.config.config_file_name:
        fileConfig(context.config.config_file_name)

    # Determine mode and run
    if context.is_offline_mode():
        run_migrations_offline()
    else:
        run_migrations_online()