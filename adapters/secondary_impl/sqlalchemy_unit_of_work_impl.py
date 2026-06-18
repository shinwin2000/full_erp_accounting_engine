#!/usr/bin/env python3
"""
Module: sqlalchemy_unit_of_work_impl.py
Layer: Adapters (Secondary Implementation)
Responsibility: Implementasi konkret dari UnitOfWorkPort menggunakan SQLAlchemy
               sebagai ORM. Mengelola session database, transaksi, dan menyediakan
               akses ke berbagai repository. Implementasi ini thread-safe dan
               mendukung async operation dengan SQLAlchemy 2.0.
Dependencies:
- sqlalchemy.ext.asyncio (AsyncSession, async_sessionmaker)
- ports.primary.unit_of_work_port (UnitOfWorkPort)
- infrastructure.database.session_factory_sqlalchemy (get_async_session_factory)
- adapters.secondary_impl.*_repository_impl (semua repository)
Audit: Setiap commit dan rollback dicatat. UoW juga bertanggung jawab untuk
       mengirim event setelah commit sukses (outbox pattern).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from adapters.secondary_impl.sqlalchemy_account_repository_impl import SQLAlchemyAccountRepository
from adapters.secondary_impl.sqlalchemy_ap_repository_impl import SQLAlchemyAPRepository
from adapters.secondary_impl.sqlalchemy_ar_repository_impl import SQLAlchemyARRepository
from adapters.secondary_impl.sqlalchemy_bank_cash_repository_impl import (
    SQLAlchemyBankCashRepository,
)
from adapters.secondary_impl.sqlalchemy_fixed_asset_repository_impl import (
    SQLAlchemyFixedAssetRepository,
)
from adapters.secondary_impl.sqlalchemy_iam_user_repository_impl import SQLAlchemyIAMUserRepository
from adapters.secondary_impl.sqlalchemy_inventory_repository_impl import (
    SQLAlchemyInventoryRepository,
)

# Repositories (akan diimplementasikan nanti)
from adapters.secondary_impl.sqlalchemy_journal_repository_impl import SQLAlchemyJournalRepository
from adapters.secondary_impl.sqlalchemy_ledger_repository_impl import SQLAlchemyLedgerRepository
from adapters.secondary_impl.sqlalchemy_legal_entity_repository_impl import (
    SQLAlchemyLegalEntityRepository,
)
from adapters.secondary_impl.sqlalchemy_outbox_repository_impl import SQLAlchemyOutboxRepository
from adapters.secondary_impl.sqlalchemy_system_setting_repository_impl import (
    SQLAlchemySystemSettingRepository,
)
from adapters.secondary_impl.sqlalchemy_tax_repository_impl import SQLAlchemyTaxRepository

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
    """Base exception untuk error UoW."""

    pass


class UnitOfWorkCommitError(UnitOfWorkError):
    """Error saat commit transaksi."""

    pass


class UnitOfWorkRollbackError(UnitOfWorkError):
    """Error saat rollback."""

    pass


# ============================================================================
# SQLALCHEMY UNIT OF WORK IMPLEMENTATION
# ============================================================================


class SQLAlchemyUnitOfWork(UnitOfWorkPort, RepositoryProvider):
    """
    Implementasi Unit of Work dengan SQLAlchemy AsyncSession.

    Fitur:
    - Mendukung async/await
    - Transaction isolation level READ COMMITTED (SERIALIZABLE untuk period closing)
    - Savepoint untuk nested transaction
    - Event collection dan publish setelah commit
    - Auto-rollback jika exception
    """

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
        """
        Args:
            session_factory: AsyncSession factory (default dari global)
            is_period_closing: Jika True, gunakan isolation level SERIALIZABLE
        """
        self._session_factory = session_factory or get_async_session_factory()
        self._session: AsyncSession | None = None
        self._repositories: dict[str, Any] = {}
        self._event_collector: list = []
        self._transaction_manager: TransactionManager | None = None
        self._savepoint_depth: int = 0
        self._is_period_closing = is_period_closing
        self._init_repositories()

    def _init_repositories(self):
        """Inisialisasi repository instances (tanpa session dulu)."""
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
        """Attach session ke semua repository."""
        for repo in self._repositories.values():
            repo.session = self._session

    async def __aenter__(self) -> SQLAlchemyUnitOfWork:
        """Memulai transaksi dan session."""
        # Buat session
        self._session = self._session_factory()

        # Set isolation level jika period closing
        if self._is_period_closing:
            await self._session.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            logger.info("UoW using SERIALIZABLE isolation for period closing")

        # Inisialisasi transaction manager
        self._transaction_manager = TransactionManager(self._session)

        # Mulai transaksi eksplisit
        await self._transaction_manager.begin()

        # Attach session ke repository
        self._attach_session_to_repositories()

        logger.debug(f"UoW started, session id: {id(self._session)}")
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any | None,
    ) -> None:
        """Keluar dari konteks, commit atau rollback."""
        try:
            if exc_type is not None:
                # Ada exception, rollback
                logger.warning(f"UoW rolling back due to exception: {exc_type.__name__}: {exc_val}")
                await self.rollback()
            else:
                # Tidak ada exception, commit dilakukan eksplisit oleh caller
                # atau auto-commit? Biarkan caller yang commit
                pass
        finally:
            # Tutup session
            if self._session:
                await self._session.close()
                logger.debug(f"UoW session closed, session id: {id(self._session)}")
            self._session = None

    async def commit(self) -> None:
        """Commit transaksi."""
        if not self._session:
            raise UnitOfWorkError("UoW not started, use async context manager")

        try:
            # Flush untuk memastikan semua perubahan terkirim ke DB
            await self._session.flush()

            # Commit transaksi
            await self._transaction_manager.commit()

            # Publish event yang terkumpul (outbox pattern)
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
        """Rollback transaksi."""
        if not self._session:
            return

        try:
            await self._transaction_manager.rollback()
            logger.info("UoW rolled back")
        except Exception as e:
            logger.error(f"Error during rollback: {e}")
            raise UnitOfWorkRollbackError(f"Rollback failed: {e}") from e
        finally:
            # Clear events
            self._event_collector.clear()

    async def flush(self) -> None:
        """Flush perubahan ke database tanpa commit."""
        if not self._session:
            raise UnitOfWorkError("UoW not started")
        await self._session.flush()

    async def execute_raw_sql(self, statement: str, params: dict[str, Any] | None = None) -> Any:
        """Execute raw SQL dalam transaksi UoW."""
        if not self._session:
            raise UnitOfWorkError("UoW not started")
        result = await self._session.execute(statement, params or {})
        return result

    async def create_savepoint(self, name: str) -> None:
        """Create savepoint untuk nested transaction."""
        if not self._session:
            raise UnitOfWorkError("UoW not started")
        await self._session.execute(f"SAVEPOINT {name}")
        self._savepoint_depth += 1
        logger.debug(f"Savepoint {name} created, depth={self._savepoint_depth}")

    async def rollback_to_savepoint(self, name: str) -> None:
        """Rollback ke savepoint."""
        if not self._session:
            raise UnitOfWorkError("UoW not started")
        await self._session.execute(f"ROLLBACK TO SAVEPOINT {name}")
        logger.debug(f"Rollback to savepoint {name}")

    async def release_savepoint(self, name: str) -> None:
        """Release savepoint."""
        if not self._session:
            raise UnitOfWorkError("UoW not started")
        await self._session.execute(f"RELEASE SAVEPOINT {name}")
        self._savepoint_depth -= 1

    def register_repository(self, name: str, repository: Any) -> None:
        """Daftarkan repository tambahan ke UoW."""
        self._repositories[name] = repository
        if self._session:
            repository.session = self._session

    def get_repository(self, name: str) -> Any:
        """Dapatkan repository yang terdaftar."""
        if name not in self._repositories:
            raise KeyError(f"Repository {name} not registered")
        return self._repositories[name]

    def add_event(self, event: Any) -> None:
        """Tambahkan event untuk dipublish setelah commit."""
        self._event_collector.append(event)

    async def _publish_events(self) -> None:
        """Publish event yang terkumpul setelah commit sukses."""
        if not self._event_collector:
            return

        logger.info(f"Publishing {len(self._event_collector)} events")

        # Gunakan outbox repository untuk menyimpan event
        outbox_repo = self.get_repository("outbox")
        for event in self._event_collector:
            await outbox_repo.save_event(event)

        # Clear collector
        self._event_collector.clear()

    # ========================================================================
    # RepositoryProvider interface
    # ========================================================================

    def journals(self) -> SQLAlchemyJournalRepository:
        return self.get_repository("journal")

    def ledger_entries(self) -> SQLAlchemyLedgerRepository:
        return self.get_repository("ledger")

    def accounts(self) -> SQLAlchemyAccountRepository:
        return self.get_repository("account")

    def ar_invoices(self) -> SQLAlchemyARRepository:
        return self.get_repository("ar")

    def ap_invoices(self) -> SQLAlchemyAPRepository:
        return self.get_repository("ap")

    def inventory(self) -> SQLAlchemyInventoryRepository:
        return self.get_repository("inventory")

    def fixed_assets(self) -> SQLAlchemyFixedAssetRepository:
        return self.get_repository("fixed_asset")

    def bank_cash(self) -> SQLAlchemyBankCashRepository:
        return self.get_repository("bank_cash")

    def tax(self) -> SQLAlchemyTaxRepository:
        return self.get_repository("tax")

    def legal_entities(self) -> SQLAlchemyLegalEntityRepository:
        return self.get_repository("legal_entity")

    def iam_users(self) -> SQLAlchemyIAMUserRepository:
        return self.get_repository("iam_user")

    def system_settings(self) -> SQLAlchemySystemSettingRepository:
        return self.get_repository("system_setting")

    # ========================================================================
    # PROPERTIES
    # ========================================================================

    @property
    async def session(self) -> AsyncSession:
        if not self._session:
            raise UnitOfWorkError("UoW not started")
        return self._session


# ============================================================================
# FACTORY
# ============================================================================


class SQLAlchemyUnitOfWorkFactory:
    """
    Factory untuk membuat instance SQLAlchemyUnitOfWork.
    Mendukung dependency injection dan konfigurasi isolation level.
    """

    def __init__(self, session_factory: async_sessionmaker | None = None):
        self._session_factory = session_factory or get_async_session_factory()

    def create(self, is_period_closing: bool = False) -> SQLAlchemyUnitOfWork:
        return SQLAlchemyUnitOfWork(
            session_factory=self._session_factory, is_period_closing=is_period_closing
        )

    @asynccontextmanager
    async def transactional(self, is_period_closing: bool = False):
        """Context manager untuk transactional UoW."""
        uow = self.create(is_period_closing)
        async with uow:
            yield uow
            await uow.commit()


# ============================================================================
# SINGLETON
# ============================================================================

_uow_factory: SQLAlchemyUnitOfWorkFactory | None = None


def get_uow_factory() -> SQLAlchemyUnitOfWorkFactory:
    global _uow_factory
    if _uow_factory is None:
        _uow_factory = SQLAlchemyUnitOfWorkFactory()
    return _uow_factory


# ============================================================================
# FASTAPI DEPENDENCY
# ============================================================================


async def get_uow() -> SQLAlchemyUnitOfWork:
    """
    Dependency untuk FastAPI endpoint.
    Mengembalikan UoW baru untuk setiap request.
    """
    factory = get_uow_factory()
    uow = factory.create()
    async with uow:
        yield uow
        # Commit akan terjadi di __aexit__ jika tidak ada exception
        # Namun caller harus memanggil commit secara eksplisit jika ingin
        # Kontrol penuh, atau kita bisa auto-commit
        # Untuk FastAPI, kita serahkan ke use case untuk commit


# ============================================================================
# ALIAS FOR TEST COMPATIBILITY (lowercase 'l')
# ============================================================================

SqlAlchemyUnitOfWork = SQLAlchemyUnitOfWork


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "SQLAlchemyUnitOfWork",
    "SQLAlchemyUnitOfWorkFactory",
    "SqlAlchemyUnitOfWork",
    "UnitOfWorkCommitError",
    "UnitOfWorkError",
    "UnitOfWorkRollbackError",
    "get_uow",
    "get_uow_factory",
]
