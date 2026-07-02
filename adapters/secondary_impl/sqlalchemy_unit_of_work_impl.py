#!/usr/bin/env python3
"""
Module: sqlalchemy_unit_of_work_impl.py
Layer: Adapters (Secondary Implementation)

Responsibility:
    Implementasi konkret dari UnitOfWorkPort menggunakan SQLAlchemy.
    Semua import dilakukan secara lazy untuk menghindari kegagalan startup
    jika ada modul infrastruktur yang belum siap.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, AsyncContextManager
from uuid import uuid4

# ============================================================================
# EXCEPTIONS (tidak perlu import eksternal)
# ============================================================================

class UnitOfWorkError(Exception):
    pass

class UnitOfWorkCommitError(UnitOfWorkError):
    pass

class UnitOfWorkRollbackError(UnitOfWorkError):
    pass


# ============================================================================
# KELAS UTAMA
# ============================================================================

class SQLAlchemyUnitOfWork:
    """
    Unit of Work dengan SQLAlchemy async session.
    Implementasi lazy import untuk semua dependensi.
    """

    __slots__ = (
        "_after_commit_hooks",
        "_after_rollback_hooks",
        "_before_commit_hooks",
        "_change_log",
        "_event_collector",
        "_is_active",
        "_is_period_closing",
        "_repositories",
        "_savepoint_depth",
        "_session",
        "_session_factory",
        "_transaction_id",
        "_transaction_manager",
        "_initialized_repos",
    )

    def __init__(
        self,
        session_factory: Any = None,  # async_sessionmaker | None
        is_period_closing: bool = False,
    ):
        self._session_factory = session_factory
        self._session: Any = None          # AsyncSession
        self._repositories: dict[str, Any] = {}
        self._event_collector: list = []
        self._transaction_manager: Any = None  # TransactionManager
        self._savepoint_depth: int = 0
        self._is_period_closing = is_period_closing
        self._before_commit_hooks: list[Callable] = []
        self._after_commit_hooks: list[Callable] = []
        self._after_rollback_hooks: list[Callable] = []
        self._change_log: list[dict[str, Any]] = []
        self._transaction_id: str | None = None
        self._is_active: bool = False
        self._initialized_repos: bool = False

    # ------------------------------------------------------------------------
    # LAZY REPOSITORY INITIALIZATION
    # ------------------------------------------------------------------------

    def _ensure_repositories_initialized(self) -> None:
        """Inisialisasi repository hanya sekali dan hanya jika dibutuhkan."""
        if self._initialized_repos:
            return

        try:
            # Semua import dilakukan di sini agar tidak mengganggu saat modul dimuat
            adapters = importlib.import_module("adapters.secondary_impl")

            # Ambil kelas-kelas repository
            account_cls = getattr(adapters, "SQLAlchemyAccountRepository", None)
            ap_cls = getattr(adapters, "SQLAlchemyAPRepository", None)
            ar_cls = getattr(adapters, "SQLAlchemyARRepository", None)
            bank_cls = getattr(adapters, "SQLAlchemyBankCashRepository", None)
            fixed_cls = getattr(adapters, "SQLAlchemyFixedAssetRepository", None)
            iam_cls = getattr(adapters, "SQLAlchemyIAMUserRepository", None)
            inv_cls = getattr(adapters, "SQLAlchemyInventoryRepository", None)
            journal_cls = getattr(adapters, "SQLAlchemyJournalRepository", None)
            ledger_cls = getattr(adapters, "SQLAlchemyLedgerRepository", None)
            legal_cls = getattr(adapters, "SQLAlchemyLegalEntityRepository", None)
            outbox_cls = getattr(adapters, "SQLAlchemyOutboxRepository", None)
            setting_cls = getattr(adapters, "SQLAlchemySystemSettingRepository", None)
            tax_cls = getattr(adapters, "SQLAlchemyTaxRepository", None)

            # Buat instance
            self._repositories["account"] = account_cls() if account_cls else None
            self._repositories["ap"] = ap_cls() if ap_cls else None
            self._repositories["ar"] = ar_cls() if ar_cls else None
            self._repositories["bank_cash"] = bank_cls() if bank_cls else None
            self._repositories["fixed_asset"] = fixed_cls() if fixed_cls else None
            self._repositories["iam_user"] = iam_cls() if iam_cls else None
            self._repositories["inventory"] = inv_cls() if inv_cls else None
            self._repositories["journal"] = journal_cls() if journal_cls else None
            self._repositories["ledger"] = ledger_cls() if ledger_cls else None
            self._repositories["legal_entity"] = legal_cls() if legal_cls else None
            self._repositories["outbox"] = outbox_cls() if outbox_cls else None
            self._repositories["system_setting"] = setting_cls() if setting_cls else None
            self._repositories["tax"] = tax_cls() if tax_cls else None

            self._initialized_repos = True
        except ImportError as e:
            raise UnitOfWorkError(f"Failed to import repository adapters: {e}") from e

    def _attach_session_to_repositories(self) -> None:
        """Set session pada setiap repository yang sudah diinisialisasi."""
        for repo in self._repositories.values():
            if repo is None:
                continue
            if hasattr(repo, "_session"):
                repo._session = self._session
            elif hasattr(repo, "session"):
                repo.session = self._session

    # ------------------------------------------------------------------------
    # LAZY SESSION FACTORY
    # ------------------------------------------------------------------------

    async def _get_session_factory(self) -> Any:
        """Mendapatkan async_sessionmaker secara lazy."""
        if self._session_factory is not None:
            return self._session_factory

        try:
            # Import infrastruktur secara lazy
            session_module = importlib.import_module(
                "infrastructure.database.session_factory_sqlalchemy"
            )
            getter = getattr(session_module, "get_async_session_factory", None)
            if getter is None:
                raise UnitOfWorkError(
                    "get_async_session_factory not found in session_factory_sqlalchemy"
                )
            # getter adalah async function
            self._session_factory = await getter()
            return self._session_factory
        except ImportError as e:
            raise UnitOfWorkError(
                f"Could not import session_factory_sqlalchemy: {e}"
            ) from e
        except Exception as e:
            raise UnitOfWorkError(
                f"Failed to get async session factory: {e}"
            ) from e

    # ------------------------------------------------------------------------
    # CONTEXT MANAGER ENTRY / EXIT
    # ------------------------------------------------------------------------

    async def __aenter__(self) -> SQLAlchemyUnitOfWork:
        if self._session_factory is None:
            self._session_factory = await self._get_session_factory()

        self._session = self._session_factory()

        if self._is_period_closing:
            await self._session.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            # logger hanya digunakan jika sudah ada, kita gunakan print atau import lazy
            try:
                from infrastructure.telemetry.structured_json_logging import get_logger
                logger = get_logger(__name__)
                logger.info("UoW using SERIALIZABLE isolation for period closing")
            except ImportError:
                pass

        # Inisialisasi TransactionManager secara lazy
        try:
            tm_module = importlib.import_module("infrastructure.database.transaction_manager")
            TransactionManager = getattr(tm_module, "TransactionManager")
            self._transaction_manager = TransactionManager(self._session)
        except ImportError as e:
            raise UnitOfWorkError(f"Could not import TransactionManager: {e}") from e

        await self._transaction_manager.begin()
        self._ensure_repositories_initialized()
        self._attach_session_to_repositories()
        self._transaction_id = str(uuid4())
        self._is_active = True

        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any | None,
    ) -> None:
        try:
            if exc_type is not None:
                await self.rollback()
        finally:
            if self._session:
                await self._session.close()
            self._session = None
            self._is_active = False

    # ------------------------------------------------------------------------
    # METODE UNIT OF WORK PORT
    # ------------------------------------------------------------------------

    async def begin(self, isolation_level: str = "READ_COMMITTED") -> None:
        """Memulai transaksi secara eksplisit."""
        if self._session is None:
            if self._session_factory is None:
                self._session_factory = await self._get_session_factory()
            self._session = self._session_factory()
            # Inisialisasi TransactionManager
            tm_module = importlib.import_module("infrastructure.database.transaction_manager")
            TransactionManager = getattr(tm_module, "TransactionManager")
            self._transaction_manager = TransactionManager(self._session)
            await self._transaction_manager.begin(isolation_level=isolation_level)
            self._ensure_repositories_initialized()
            self._attach_session_to_repositories()
            self._transaction_id = str(uuid4())
            self._is_active = True
        else:
            # Sudah ada transaksi, abaikan
            pass

    async def begin_read_only(self) -> None:
        """Memulai transaksi read-only."""
        await self.begin(isolation_level="READ COMMITTED")
        if self._session:
            await self._session.execute("SET TRANSACTION READ ONLY")

    async def commit(self) -> None:
        if not self._session:
            raise UnitOfWorkError("UoW not started, use async context manager or call begin()")

        try:
            # Before hooks
            for hook in self._before_commit_hooks:
                if callable(hook):
                    if hasattr(hook, "__await__"):
                        await hook()
                    else:
                        hook()

            await self._session.flush()
            await self._transaction_manager.commit()
            await self._publish_events()

            # After hooks
            for hook in self._after_commit_hooks:
                if callable(hook):
                    if hasattr(hook, "__await__"):
                        await hook()
                    else:
                        hook()

            self._is_active = False
        except Exception as e:
            await self.rollback()
            raise UnitOfWorkCommitError(f"Commit failed: {e}") from e

    async def rollback(self) -> None:
        if not self._session:
            return
        try:
            await self._transaction_manager.rollback()
            for hook in self._after_rollback_hooks:
                if callable(hook):
                    if hasattr(hook, "__await__"):
                        await hook()
                    else:
                        hook()
            self._is_active = False
        except Exception as e:
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

    # ------------------------------------------------------------------------
    # SAVEPOINT
    # ------------------------------------------------------------------------

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

    @asynccontextmanager
    async def savepoint(self, name: str) -> AsyncContextManager:
        if not self._session:
            raise UnitOfWorkError("UoW not started")
        await self.create_savepoint(name)
        try:
            yield
            await self.release_savepoint(name)
        except Exception:
            await self.rollback_to_savepoint(name)
            raise

    @asynccontextmanager
    async def transaction(self) -> AsyncContextManager:
        if not self._session:
            raise UnitOfWorkError("UoW not started")
        sp_name = f"sp_{uuid4().hex[:8]}"
        async with self.savepoint(sp_name):
            yield

    # ------------------------------------------------------------------------
    # HOOKS
    # ------------------------------------------------------------------------

    def add_before_commit_hook(self, hook: Callable) -> None:
        if callable(hook):
            self._before_commit_hooks.append(hook)

    def add_after_commit_hook(self, hook: Callable) -> None:
        if callable(hook):
            self._after_commit_hooks.append(hook)

    def add_after_rollback_hook(self, hook: Callable) -> None:
        if callable(hook):
            self._after_rollback_hooks.append(hook)

    # ------------------------------------------------------------------------
    # TRANSACTION INFO  (FIX: async versions)
    # ------------------------------------------------------------------------

    async def get_transaction_id(self) -> str | None:
        """Ambil ID transaksi saat ini (async version)."""
        return self._transaction_id

    async def get_isolation_level(self) -> str:
        """Ambil level isolasi transaksi saat ini (async version)."""
        if not self._session:
            return "UNKNOWN"
        try:
            result = await self._session.execute("SHOW transaction_isolation")
            return result.scalar()
        except Exception:
            return "READ_COMMITTED"

    async def is_active(self) -> bool:
        """Cek apakah transaksi aktif (async version)."""
        return self._is_active and self._session is not None

    # ------------------------------------------------------------------------
    # CHANGE LOGGING
    # ------------------------------------------------------------------------

    def record_change(self, entity: Any, change_type: str) -> None:
        self._change_log.append({
            "entity": str(entity),
            "change_type": change_type,
            "timestamp": datetime.utcnow().isoformat(),
        })
        if len(self._change_log) > 1000:
            self._change_log = self._change_log[-500:]

    # ------------------------------------------------------------------------
    # REPOSITORY MANAGEMENT
    # ------------------------------------------------------------------------

    def register_repository(self, name: str, repository: Any) -> None:
        self._repositories[name] = repository
        if self._session:
            if hasattr(repository, "_session"):
                repository._session = self._session
            elif hasattr(repository, "session"):
                repository.session = self._session

    def get_repository(self, name: str) -> Any:
        if name not in self._repositories:
            raise KeyError(f"Repository '{name}' not registered")
        return self._repositories[name]

    def add_event(self, event: Any) -> None:
        self._event_collector.append(event)

    async def _publish_events(self) -> None:
        if not self._event_collector:
            return

        outbox_repo = self.get_repository("outbox")
        if outbox_repo is None:
            # Tidak ada outbox repository, lewatkan
            return

        for event in self._event_collector:
            if hasattr(outbox_repo, "save_event"):
                await outbox_repo.save_event(event)
            else:
                # fallback: simpan ke atribut event collector
                pass

        self._event_collector.clear()

    # ------------------------------------------------------------------------
    # RepositoryProvider interface (convenience)
    # ------------------------------------------------------------------------

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
    async def session(self):
        if not self._session:
            raise UnitOfWorkError("UoW not started")
        return self._session


# ============================================================================
# FACTORY
# ============================================================================

class SQLAlchemyUnitOfWorkFactory:
    def __init__(self, session_factory: Any = None):
        self._session_factory = session_factory

    def create(self, is_period_closing: bool = False) -> SQLAlchemyUnitOfWork:
        return SQLAlchemyUnitOfWork(
            session_factory=self._session_factory,
            is_period_closing=is_period_closing,
        )

    @asynccontextmanager
    async def transactional(self, is_period_closing: bool = False):
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

async def get_uow() -> SQLAlchemyUnitOfWork:
    factory = get_uow_factory()
    uow = factory.create()
    async with uow:
        return uow


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