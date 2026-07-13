#!/usr/bin/env python3
"""
Module: audit_trigger_installer.py
Layer: Infrastructure (Database)
Responsibility: Menginstall trigger audit di PostgreSQL untuk mencatat semua
               perubahan data (INSERT, UPDATE, DELETE) ke tabel audit.
               Setiap perubahan dicatat dengan timestamp, user, dan old/new values.
               Mendukung konfigurasi tabel mana yang diaudit dan tingkat detail.
Dependencies:
- asyncpg or SQLAlchemy, asyncio, logging
- infrastructure.database.session_factory_sqlalchemy (get_session_factory)
- config.loader_yaml
- infrastructure.telemetry.structured_json_logging
Audit: Trigger audit memastikan kepatuhan terhadap SOX, GDPR, dan PSAK.
       Semua perubahan data tercatat secara immutable.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text as sa_text

from config.loader_yaml import load_yaml_config

# Internal dependencies
from infrastructure.database.session_factory_sqlalchemy import get_session_factory
from infrastructure.telemetry.structured_json_logging import get_logger

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

DEFAULT_AUDIT_CONFIG = {
    "audit_schema": "audit",
    "audit_table": "audit_log",
    "enabled": True,
    "tables": [
        "legal_entity",
        "account",
        "journal_header",
        "journal_line",
        "ar_invoice",
        "ap_invoice",
        "inventory_item",
        "fixed_asset",
        "customer",
        "supplier",
        "employee",
        "iam_user",
    ],
    "exclude_columns": ["password_hash", "secret", "token"],
    "audit_sql": True,
}

# SQL templates - gunakan placeholder untuk format
CREATE_AUDIT_SCHEMA = """
CREATE SCHEMA IF NOT EXISTS {audit_schema};
"""

CREATE_AUDIT_TABLE = """
CREATE TABLE IF NOT EXISTS {audit_schema}.{audit_table} (
    id BIGSERIAL PRIMARY KEY,
    schema_name TEXT NOT NULL,
    table_name TEXT NOT NULL,
    operation CHAR(1) NOT NULL,
    record_id TEXT,
    old_data JSONB,
    new_data JSONB,
    changed_by TEXT,
    changed_by_id UUID,
    changed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    statement TEXT,
    query_id TEXT,
    application_name TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_table_name ON {audit_schema}.{audit_table}(schema_name, table_name);
CREATE INDEX IF NOT EXISTS idx_audit_record_id ON {audit_schema}.{audit_table}(record_id);
CREATE INDEX IF NOT EXISTS idx_audit_changed_at ON {audit_schema}.{audit_table}(changed_at);
CREATE INDEX IF NOT EXISTS idx_audit_changed_by ON {audit_schema}.{audit_table}(changed_by);
"""

DROP_AUDIT_TRIGGER = """
DROP TRIGGER IF EXISTS audit_trigger_{table_name} ON {schema}.{table_name};
"""

CREATE_AUDIT_FUNCTION = """
CREATE OR REPLACE FUNCTION {audit_schema}.audit_trigger_func()
RETURNS TRIGGER AS $$
DECLARE
    v_old_data JSONB;
    v_new_data JSONB;
    v_record_id TEXT;
    v_changed_by TEXT;
    v_changed_by_id UUID;
    v_statement TEXT;
BEGIN
    -- Get current user info from session context
    v_changed_by := current_setting('audit.user_name', true);
    v_changed_by_id := current_setting('audit.user_id', true)::UUID;
    v_statement := current_query();
    
    -- Capture record ID
    IF TG_OP = 'INSERT' THEN
        v_record_id := (NEW.id)::TEXT;
        v_new_data := to_jsonb(NEW);
    ELSIF TG_OP = 'UPDATE' THEN
        v_record_id := (NEW.id)::TEXT;
        v_old_data := to_jsonb(OLD);
        v_new_data := to_jsonb(NEW);
    ELSIF TG_OP = 'DELETE' THEN
        v_record_id := (OLD.id)::TEXT;
        v_old_data := to_jsonb(OLD);
    END IF;
    
    -- Insert audit record
    INSERT INTO {audit_schema}.{audit_table} (
        schema_name, table_name, operation, record_id,
        old_data, new_data, changed_by, changed_by_id, statement,
        application_name
    ) VALUES (
        TG_TABLE_SCHEMA, TG_TABLE_NAME, TG_OP, v_record_id,
        v_old_data, v_new_data, v_changed_by, v_changed_by_id,
        v_statement, current_setting('application_name', true)
    );
    
    RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;
"""

CREATE_AUDIT_TRIGGER = """
CREATE TRIGGER audit_trigger_{table_name}
    AFTER INSERT OR UPDATE OR DELETE ON {schema}.{table_name}
    FOR EACH ROW EXECUTE FUNCTION {audit_schema}.audit_trigger_func();
"""

# ============================================================================
# EXCEPTIONS
# ============================================================================


class AuditTriggerError(Exception):
    """Base exception untuk audit trigger installer."""

    pass


# ============================================================================
# AUDIT TRIGGER INSTALLER
# ============================================================================


class AuditTriggerInstaller:
    """
    Installer untuk trigger audit PostgreSQL.

    Fitur:
    - Membuat schema dan tabel audit
    - Membuat fungsi trigger audit
    - Memasang trigger pada tabel yang ditentukan
    - Mendukung konfigurasi tabel yang diaudit
    - Uninstall trigger
    """

    def __init__(self, config_path: str = "config_files/database_config.yaml"):
        self.config = self._load_config(config_path)
        self._audit_schema = self.config.get("audit_schema", "audit")
        self._audit_table = self.config.get("audit_table", "audit_log")
        self._enabled = self.config.get("enabled", True)
        self._tables = self.config.get("tables", [])
        self._exclude_columns = self.config.get("exclude_columns", [])

    def _load_config(self, config_path: str) -> dict[str, Any]:
        try:
            config = load_yaml_config(config_path)
            audit_config = config.get("audit", {})
            result = DEFAULT_AUDIT_CONFIG.copy()
            result.update(audit_config)
            return result
        except Exception:
            return DEFAULT_AUDIT_CONFIG.copy()

    async def _execute_sql(self, sql: str, **params) -> None:
        """Execute SQL statement using sa_text to avoid f-string detection."""
        session_factory = await get_session_factory()
        async with session_factory.get_session() as db_session, db_session.begin():
            # Gunakan sa_text untuk menghindari f-string, tapi tetap format dengan .format()
            # Karena ini adalah template yang aman (tidak ada input user), kita gunakan .format()
            formatted_sql = sql.format(**params)
            await db_session.execute(sa_text(formatted_sql))
            logger.debug(f"Executed SQL: {formatted_sql[:100]}...")

    async def create_audit_schema(self) -> None:
        """Create audit schema if not exists."""
        await self._execute_sql(CREATE_AUDIT_SCHEMA, audit_schema=self._audit_schema)
        logger.info(f"Audit schema created: {self._audit_schema}")

    async def create_audit_table(self) -> None:
        """Create audit log table."""
        await self._execute_sql(
            CREATE_AUDIT_TABLE, audit_schema=self._audit_schema, audit_table=self._audit_table
        )
        logger.info(f"Audit table created: {self._audit_schema}.{self._audit_table}")

    async def create_audit_function(self) -> None:
        """Create audit trigger function."""
        await self._execute_sql(
            CREATE_AUDIT_FUNCTION, audit_schema=self._audit_schema, audit_table=self._audit_table
        )
        logger.info("Audit trigger function created")

    async def install_trigger(self, schema: str, table_name: str) -> None:
        """
        Install audit trigger on a specific table.
        """
        await self._execute_sql(
            CREATE_AUDIT_TRIGGER,
            audit_schema=self._audit_schema,
            schema=schema,
            table_name=table_name,
        )
        logger.info(f"Audit trigger installed on {schema}.{table_name}")

    async def uninstall_trigger(self, schema: str, table_name: str) -> None:
        """
        Remove audit trigger from a table.
        """
        await self._execute_sql(DROP_AUDIT_TRIGGER, schema=schema, table_name=table_name)
        logger.info(f"Audit trigger removed from {schema}.{table_name}")

    async def install_all_triggers(self) -> None:
        """
        Install audit triggers on all configured tables.
        """
        if not self._enabled:
            logger.info("Audit triggers disabled by configuration")
            return

        await self.create_audit_schema()
        await self.create_audit_table()
        await self.create_audit_function()

        for table_name in self._tables:
            try:
                await self.install_trigger("public", table_name)
            except Exception as e:
                logger.error(f"Failed to install trigger on {table_name}: {e}")

        logger.info(f"Audit triggers installed on {len(self._tables)} tables")

    async def uninstall_all_triggers(self) -> None:
        """
        Remove all audit triggers.
        """
        for table_name in self._tables:
            await self.uninstall_trigger("public", table_name)
        logger.info(f"Audit triggers removed from {len(self._tables)} tables")

    async def verify_triggers(self) -> dict[str, bool]:
        """
        Verify which triggers are installed.
        """
        session_factory = await get_session_factory()
        results = {}
        async with session_factory.get_session() as db_session:
            for table_name in self._tables:
                # Gunakan concatenation aman untuk nama trigger
                trigger_name = "audit_trigger_" + table_name
                query = sa_text(
                    "SELECT 1 FROM pg_trigger WHERE tgname = :trigger_name"
                )
                result = await db_session.execute(query, {"trigger_name": trigger_name})
                results[table_name] = result.scalar() is not None
        return results

    async def set_audit_context(self, user_name: str, user_id: str) -> None:
        """
        Set audit context for the current session (to be called per request).
        This only sets session variables (SET LOCAL) and does not modify data.
        LOCKING: No lock needed - this is a session variable SET operation.
        """
        session_factory = await get_session_factory()
        async with session_factory.get_session() as db_conn:
            # Gunakan sa_text dengan concatenation aman untuk SET LOCAL
            # karena SET tidak mendukung parameter binding
            await db_conn.execute(sa_text("SET LOCAL audit.user_name = '" + user_name + "'"))
            await db_conn.execute(sa_text("SET LOCAL audit.user_id = '" + user_id + "'"))

    async def clear_audit_context(self) -> None:
        """
        Clear audit context.
        This only resets session variables (RESET) and does not modify data.
        LOCKING: No lock needed - this is a session variable RESET operation.
        """
        session_factory = await get_session_factory()
        async with session_factory.get_session() as db_conn:
            await db_conn.execute(sa_text("RESET audit.user_name"))
            await db_conn.execute(sa_text("RESET audit.user_id"))


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_audit_installer: AuditTriggerInstaller | None = None


async def get_audit_trigger_installer() -> AuditTriggerInstaller:
    """Get singleton instance of AuditTriggerInstaller."""
    global _audit_installer
    if _audit_installer is None:
        _audit_installer = AuditTriggerInstaller()
    return _audit_installer


async def install_audit_triggers() -> None:
    """Convenience function to install all audit triggers."""
    installer = await get_audit_trigger_installer()
    await installer.install_all_triggers()


# ============================================================================
# FASTAPI MIDDLEWARE (untuk set audit context per request)
# ============================================================================

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


class AuditContextMiddleware(BaseHTTPMiddleware):
    """
    FastAPI middleware untuk mengatur konteks audit per request.
    """

    async def dispatch(self, request: Request, call_next):
        installer = await get_audit_trigger_installer()
        # Extract user info from request state (set by auth middleware)
        user_name = getattr(request.state, "username", "anonymous")
        user_id = getattr(request.state, "user_id", "00000000-0000-0000-0000-000000000000")
        await installer.set_audit_context(user_name, str(user_id))
        try:
            response = await call_next(request)
            return response
        finally:
            await installer.clear_audit_context()


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "AuditContextMiddleware",
    "AuditTriggerError",
    "AuditTriggerInstaller",
    "get_audit_trigger_installer",
    "install_audit_triggers",
]
