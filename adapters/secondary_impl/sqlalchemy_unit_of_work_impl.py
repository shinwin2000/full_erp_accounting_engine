#!/usr/bin/env python3
"""
Module: sqlalchemy_unit_of_work_impl.py
Layer: Adapters (Secondary Implementation)
Responsibility: Implementasi konkret dari UnitOfWorkPort menggunakan SQLAlchemy
               sebagai ORM. Menggunakan lazy imports untuk repo adapters.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# Infrastructure
from infrastructure.database.session_factory_sqlalchemy import get_async_session_factory
from infrastructure.database.transaction_manager import TransactionManager
from infrastructure.telemetry.structured_json_logging import get_logger

# Ports
from ports.primary.unit_of_work_port import RepositoryProvider, UnitOfWorkPort

logger = get_logger(__name__)


# ============================================================================
# EXCEPTIONS
# ============================================================================

class UnitOfWorkError(Exception):
    pass

class UnitOfWorkCommitError(UnitOfWorkError):
    pass

class UnitOfWorkRollbackError(UnitOfWorkError):
    pass


# ============================================================================
# SQLALCHEMY UNIT OF WORK IMPLEMENTATION
# ============================================================================

class SQLAlchemyUnitOfWork(UnitOfWorkPort, RepositoryProvider):
    __slots__ = (
        "_event_collector",
        "_is_period_closing",
        "_repositories",
        "_savepoint_depth",
        "_session",
        "_session_factory",
        "_transaction_manager",
    )

    def __init__(
        self, session_factory: async_sessionmaker | None = None, is_period_closing: bool = False
    ):
        self._session_factory = session_factory
        self._session: AsyncSession | None = None
        self._repositories: dict[str, Any] = {}
        self._event_collector: list = []
        self._transaction_manager: TransactionManager | None = None
        self._savepoint_depth: int = 0
        self._is_period_closing = is_period_closing
        self._init_repositories()

    def _init_repositories(self):
        """Inisialisasi repository instances menggunakan lazy imports."""
        from adapters.secondary_impl.sqlalchemy_account_repository_impl import (
            SQLAlchemyAccountRepository,
        )
        from adapters.secondary_impl.sqlalchemy_ap_repository_impl import SQLAlchemyAPRepository
        from adapters.secondary_impl.sqlalchemy_ar_repository_impl import SQLAlchemyARRepository
        from adapters.secondary_impl.sqlalchemy_bank_cash_repository_impl import (
            SQLAlchemyBankCashRepository,
        )
        from adapters.secondary_impl.sqlalchemy_fixed_asset_repository_impl import (
            SQLAlchemyFixedAssetRepository,
        )
        from adapters.secondary_impl.sqlalchemy_iam_user_repository_impl import (
            SQLAlchemyIAMUserRepository,
        )
        from adapters.secondary_impl.sqlalchemy_inventory_repository_impl import (
            SQLAlchemyInventoryRepository,
        )
        from adapters.secondary_impl.sqlalchemy_journal_repository_impl import (
            SQLAlchemyJournalRepository,
        )
        from adapters.secondary_impl.sqlalchemy_ledger_repository_impl import (
            SQLAlchemyLedgerRepository,
        )
        from adapters.secondary_impl.sqlalchemy_legal_entity_repository_impl import (
            SQLAlchemyLegalEntityRepository,
        )
        from adapters.secondary_impl.sqlalchemy_outbox_repository_impl import (
            SQLAlchemyOutboxRepository,
        )
        from adapters.secondary_impl.sqlalchemy_system_setting_repository_impl import (
            SQLAlchemySystemSettingRepository,
        )
        from adapters.secondary_impl.sqlalchemy_tax_repository_impl import SQLAlchemyTaxRepository

        self._repositories["journal"] = SQLAlchemyJournalRepository()
        self._repositories["ledger"] = SQLAlchemyLedgerRepository()
        self._repositories["account"] = SQLAlchemyAccountRepository()
        self._repositories["ar"] = SQLAlchemyARRepository()
        self._repositories["ap"] = SQLAlchemyAPRepository()
        self._repositories["inventory"] = SQLAlchemyInventoryRepository()
        self._repositories["fixed_asset"] = SQLAlchemyFixedAssetRepository()
        self._repositories["bank_cash"] = SQLAlchemyBankCashRepository()
        self._repositories["tax"] = SQLAlchemyTaxRepository()
        self._repositories["legal_entity"] = SQLAlchemyLegalEntityRepository()
        self._repositories["iam_user"] = SQLAlchemyIAMUserRepository()
        self._repositories["system_setting"] = SQLAlchemySystemSettingRepository()
        self._repositories["outbox"] = SQLAlchemyOutboxRepository()

    def _attach_session_to_repositories(self):
        for repo in self._repositories.values():
            repo.session = self._session

    async def __aenter__(self) -> SQLAlchemyUnitOfWork:
        if self._session_factory is None:
            self._session_factory = get_async_session_factory()

        self._session = self._session_factory()

        if self._is_period_closing:
            await self._session.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            logger.info("UoW using SERIALIZABLE isolation for period closing")

        self._transaction_manager = TransactionManager(self._session)
        await self._transaction_manager.begin()
        self._attach_session_to_repositories()

        logger.debug(f"UoW started, session id: {id(self._session)}")
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any | None,
    ) -> None:
        try:
            if exc_type is not None:
                logger.warning(f"UoW rolling back due to exception: {exc_type.__name__}: {exc_val}")
                await self.rollback()
        finally:
            if self._session:
                await self._session.close()
                logger.debug(f"UoW session closed, session id: {id(self._session)}")
            self._session = None

    # ========================================================================
    # METODE YANG DIBUTUHKAN OLEH UnitOfWorkPort (P55 CONTRACT)
    # ========================================================================

    async def begin(self, isolation_level: str = "READ_COMMITTED") -> None:
        """
        Begin a transaction with optional isolation level.
        This method is required by UnitOfWorkPort interface.
        """
        if self._session is None:
            if self._session_factory is None:
                self._session_factory = get_async_session_factory()
            self._session = self._session_factory()
        if self._transaction_manager is None:
            self._transaction_manager = TransactionManager(self._session)
            await self._transaction_manager.begin(isolation_level=isolation_level)
            self._attach_session_to_repositories()
        else:
            logger.debug("Transaction already begun, ignoring begin() call")

    async def begin_read_only(self) -> None:
        """
        Begin a read-only transaction.
        Required by UnitOfWorkPort interface.
        """
        await self.begin(isolation_level="READ COMMITTED")
        if self._session:
            # Set session to read-only if supported
            await self._session.execute("SET TRANSACTION READ ONLY")
            logger.debug("Read-only transaction begun")

    # ========================================================================
    # METODE LAINNYA (commit, rollback, flush, dll)
    # ========================================================================

    async def commit(self) -> None:
        if not self._session:
            raise UnitOfWorkError("UoW not started, use async context manager")

        try:
            await self._session.flush()
            await self._transaction_manager.commit()
            await self._publish_events()
            logger.info("UoW committed successfully")
        except IntegrityError as e:
            await self.rollback()
            logger.error(f"Integrity error during commit: {e}")
            raise UnitOfWorkCommitError(f"Database integrity error: {e}") from e
        except SQLAlchemyError as e:
            await self.rollback()
            logger.error(f"SQLAlchemy error during commit: {e}")
            raise UnitOfWorkCommitError(f"Database error: {e}") from e
        except Exception as e:
            await self.rollback()
            logger.exception(f"Unexpected error during commit: {e}")
            raise UnitOfWorkCommitError(f"Unexpected error: {e}") from e

    async def rollback(self) -> None:
        if not self._session:
            return

        try:
            await self._transaction_manager.rollback()
            logger.info("UoW rolled back")
        except Exception as e:
            logger.error(f"Error during rollback: {e}")
            raise UnitOfWorkRollbackError(f"Rollback failed: {e}") from e
        finally:
            self._event_collector.clear()

    async def flush(self) -> None:
        if not self._session:
            raise UnitOfWorkError("UoW not started")
        await self._session.flush()

    async def execute_raw_sql(self, statement: str, params: dict[str, Any] | None = None) -> Any:
        if not self._session:
            raise UnitOfWorkError("UoW not started")
        return await self._session.execute(statement, params or {})

    async def create_savepoint(self, name: str) -> None:
        if not self._session:
            raise UnitOfWorkError("UoW not started")
        await self._session.execute(f"SAVEPOINT {name}")
        self._savepoint_depth += 1

    async def rollback_to_savepoint(self, name: str) -> None:
        if not self._session:
            raise UnitOfWorkError("UoW not started")
        await self._session.execute(f"ROLLBACK TO SAVEPOINT {name}")

    async def release_savepoint(self, name: str) -> None:
        if not self._session:
            raise UnitOfWorkError("UoW not started")
        await self._session.execute(f"RELEASE SAVEPOINT {name}")
        self._savepoint_depth -= 1

    def register_repository(self, name: str, repository: Any) -> None:
        self._repositories[name] = repository
        if self._session:
            repository.session = self._session

    def get_repository(self, name: str) -> Any:
        if name not in self._repositories:
            raise KeyError(f"Repository {name} not registered")
        return self._repositories[name]

    def add_event(self, event: Any) -> None:
        self._event_collector.append(event)

    async def _publish_events(self) -> None:
        if not self._event_collector:
            return

        outbox_repo = self.get_repository("outbox")
        for event in self._event_collector:
            await outbox_repo.save_event(event)

        self._event_collector.clear()

    # ========================================================================
    # RepositoryProvider interface
    # ========================================================================

    def journals(self): return self.get_repository("journal")
    def ledger_entries(self): return self.get_repository("ledger")
    def accounts(self): return self.get_repository("account")
    def ar_invoices(self): return self.get_repository("ar")
    def ap_invoices(self): return self.get_repository("ap")
    def inventory(self): return self.get_repository("inventory")
    def fixed_assets(self): return self.get_repository("fixed_asset")
    def bank_cash(self): return self.get_repository("bank_cash")
    def tax(self): return self.get_repository("tax")
    def legal_entities(self): return self.get_repository("legal_entity")
    def iam_users(self): return self.get_repository("iam_user")
    def system_settings(self): return self.get_repository("system_setting")

    @property
    async def session(self) -> AsyncSession:
        if not self._session:
            raise UnitOfWorkError("UoW not started")
        return self._session


# ============================================================================
# FACTORY
# ============================================================================

class SQLAlchemyUnitOfWorkFactory:
    def __init__(self, session_factory: async_sessionmaker | None = None):
        self._session_factory = session_factory or get_async_session_factory()

    def create(self, is_period_closing: bool = False) -> SQLAlchemyUnitOfWork:
        return SQLAlchemyUnitOfWork(
            session_factory=self._session_factory, is_period_closing=is_period_closing
        )

    @asynccontextmanager
    async def transactional(self, is_period_closing: bool = False):
        uow = self.create(is_period_closing)
        async with uow:
            yield uow
            await uow.commit()


# ============================================================================
# SINGLETON & DEPENDENCY
# ============================================================================

_uow_factory: SQLAlchemyUnitOfWorkFactory | None = None

def get_uow_factory() -> SQLAlchemyUnitOfWorkFactory:
    global _uow_factory
    if _uow_factory is None:
        _uow_factory = SQLAlchemyUnitOfWorkFactory()
    return _uow_factory


async def get_uow() -> SQLAlchemyUnitOfWork:
    factory = get_uow_factory()
    uow = factory.create()
    async with uow:
        yield uow


# ============================================================================
# ALIAS UNTUK KOMPATIBILITAS
# ============================================================================

SQLAlchemyUnitOfWorkImpl = SQLAlchemyUnitOfWork
SqlAlchemyUnitOfWork = SQLAlchemyUnitOfWork


__all__ = [
    "SQLAlchemyUnitOfWork",
    "SQLAlchemyUnitOfWorkFactory",
    "SQLAlchemyUnitOfWorkImpl",
    "SqlAlchemyUnitOfWork",
    "UnitOfWorkCommitError",
    "UnitOfWorkError",
    "UnitOfWorkRollbackError",
    "get_uow",
    "get_uow_factory",
]