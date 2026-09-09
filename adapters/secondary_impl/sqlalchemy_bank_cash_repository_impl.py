#!/usr/bin/env python3
"""
Module: sqlalchemy_bank_cash_repository_impl.py
Layer: Adapters (Secondary Implementation)
Responsibility: Implementasi repository untuk Bank & Cash Management menggunakan
               SQLAlchemy ORM. Menyediakan operasi CRUD untuk bank account,
               cash book, petty cash fund, bank transactions, bank reconciliation,
               dan cash flow tracking. Mendukung multiple currency, soft delete,
               dan optimistic locking untuk bank account master.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import and_, case, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

# Domain
from domain.bank_cash.bank_account_entity import BankAccountEntity, BankAccountStatus, BankAccountType
from domain.bank_cash.bank_aggregate_root import (
    BankReconciliation,
    BankTransaction,
    BankTransactionStatus,
    BankTransactionType,
)

# Value objects
from domain.shared_value_objects.money_vo import Money

# Infrastructure ORM
from infrastructure.persistence_orm.bank_account_table import BankAccountTable
from infrastructure.persistence_orm.bank_reconciliation_table import BankReconciliationTable
from infrastructure.persistence_orm.bank_transaction_table import BankTransactionTable
from infrastructure.persistence_orm.cash_book_table import CashBookTable
from infrastructure.persistence_orm.petty_cash_fund_table import PettyCashFundTable

# Ports
from ports.primary.bank_cash_repository_port import BankAccountRepositoryPort

logger = logging.getLogger(__name__)


@dataclass
class CashBookRecord:
    """Representasi satu baris tabel `cash_book` (1 baris per legal_entity +
    currency_code). `CashBookAggregate` (alias dari `CashAggregate` di
    domain/bank_cash/cash_aggregate_root.py) TIDAK dipakai di sini karena
    bentuknya beda total (dia agregat besar berisi banyak cash book dalam
    dict, bukan satu baris) -- memakainya di sini menyebabkan TypeError
    begitu ada data asli untuk dikonversi."""

    id: UUID
    legal_entity_id: UUID
    currency_code: str
    current_balance: Decimal
    opening_balance: Decimal
    opening_balance_date: date
    gl_cash_account_id: UUID | None
    gl_bank_account_id: UUID | None
    last_updated: datetime
    created_at: datetime
    created_by: UUID | None
    version: int = 1
    # Tidak dipersist ke DB (tidak ada kolomnya di tabel `cash_book`) --
    # hilang setelah restart aplikasi kalau butuh permanen, perlu migration.
    is_closed: bool = False
    closed_at: datetime | None = None
    closed_by: UUID | None = None


@dataclass
class PettyCashFund:
    """Model flat sederhana untuk satu dana petty cash - field-nya cocok
    dengan kolom tabel `petty_cash_fund` SUNGGUHAN (lihat
    infrastructure/persistence_orm/petty_cash_fund_table.py). Dipakai
    (bukan `PettyCashFundEntity` di
    domain/bank_cash/petty_cash_fund_entity.py) karena entity itu
    bentuknya beda total (custodian diidentifikasi lewat nama bukan ID,
    tidak ada field gl_account_id, dst) - memakainya menyebabkan
    TypeError begitu ada data asli untuk dikonversi. service_bank_cash.py
    meng-import class ini dari sini, mengikuti pola yang sama seperti
    CashBookRecord di atas."""

    id: UUID
    legal_entity_id: UUID
    fund_name: str
    currency_code: str = "IDR"
    initial_amount: Decimal = Decimal("0")
    current_balance: Decimal = Decimal("0")
    custodian_id: UUID | None = None
    gl_account_id: UUID | None = None
    reimbursement_threshold: Decimal = Decimal("1000000")
    fund_location: str | None = None
    notes: str | None = None
    status: str = "active"
    is_active: bool = True
    is_closed: bool = False
    created_by: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    updated_by: UUID | None = None
    last_replenishment_date: date | None = None
    activated_at: datetime | None = None
    activated_by: UUID | None = None
    closed_at: datetime | None = None
    closed_by: UUID | None = None
    suspended_at: datetime | None = None
    suspended_by: UUID | None = None
    suspend_reason: str | None = None
    version: int = 1
    custodian_name: str | None = None
    created_by_name: str | None = None


# ============================================================================
# CONSTANTS
# ============================================================================

DEFAULT_CURRENCY = "IDR"

# ============================================================================
# EXCEPTIONS
# ============================================================================


class BankCashRepositoryError(Exception):
    """Base exception untuk repository bank & cash."""
    pass


class DuplicateAccountNumberError(BankCashRepositoryError):
    """Nomor rekening sudah ada."""
    pass


class BankAccountNotFoundError(BankCashRepositoryError):
    """Rekening bank tidak ditemukan."""
    pass


class CashBookNotFoundError(BankCashRepositoryError):
    """Cash book tidak ditemukan."""
    pass


class InsufficientBalanceError(BankCashRepositoryError):
    """Saldo tidak mencukupi untuk transaksi."""
    pass


class ReconciliationNotFoundError(BankCashRepositoryError):
    """Rekonsiliasi tidak ditemukan."""
    pass


class OptimisticLockError(BankCashRepositoryError):
    """Version mismatch saat update."""
    pass


# ============================================================================
# REPOSITORY IMPLEMENTATION
# ============================================================================


class SQLAlchemyBankAccountRepository(BankAccountRepositoryPort):
    """
    Implementasi repository Bank & Cash dengan SQLAlchemy.
    Mengimplementasi BankAccountRepositoryPort.
    """

    def __init__(self, session: AsyncSession | None = None):
        self._session = None
        if session is not None:
            if hasattr(session, "session"):
                self._session = session.session
            else:
                self._session = session

    @property
    def session(self) -> AsyncSession:
        if self._session is None:
            raise BankCashRepositoryError("Session not set")
        return self._session

    @session.setter
    def session(self, value: AsyncSession) -> None:
        self._session = value

    # ========================================================================
    # HELPER MAPPING METHODS - BANK ACCOUNT
    # ========================================================================

    def _to_domain_bank_account(self, table: BankAccountTable) -> BankAccountEntity:
        return BankAccountEntity(
            account_id=table.id,
            account_number=table.account_number,
            bank_name=table.bank_name,
            bank_code=table.bank_code,
            account_name=table.account_name,
            account_type=BankAccountType(table.account_type),
            branch_name=None,  # tidak ada kolom `branch` di tabel bank_account saat ini
            currency=table.currency_code,
            current_balance=table.current_balance,
            available_balance=table.available_balance,
            gl_account_id=table.gl_account_id,
            is_active=table.is_active,
            is_default=table.is_default,
            status=BankAccountStatus(table.status),
            opening_balance=table.opening_balance,
            opening_balance_date=table.opening_balance_date,
            last_reconciled_date=table.last_reconciliation_date,
            created_at=table.created_at,
            updated_at=table.updated_at,
            created_by=table.created_by,
            version=table.version,
            legal_entity_id=table.legal_entity_id,
            deleted_at=table.deleted_at,
        )

    async def _to_orm_bank_account(self, account: BankAccountEntity) -> BankAccountTable:
        status_str = (
            account.status.value if hasattr(account.status, "value") else str(account.status)
        )
        account_type_str = (
            account.account_type.value if hasattr(account.account_type, "value") else str(account.account_type)
        )

        return BankAccountTable(
            id=account.account_id,
            account_number=account.account_number,
            bank_name=account.bank_name,
            bank_code=account.bank_code,
            account_name=account.account_name,
            currency_code=account.currency,
            account_type=account_type_str,
            current_balance=account.current_balance,
            available_balance=account.available_balance,
            gl_account_id=account.gl_account_id,
            is_active=account.is_active,
            is_default=account.is_default,
            status=status_str,
            opening_balance=account.opening_balance,
            opening_balance_date=account.opening_balance_date,
            last_reconciliation_date=account.last_reconciled_date,
            created_at=account.created_at,
            updated_at=datetime.utcnow(),
            created_by=account.created_by,
            version=account.version,
            legal_entity_id=account.legal_entity_id,
        )

    # ========================================================================
    # HELPER MAPPING METHODS - BANK TRANSACTION
    # ========================================================================

    def _to_domain_transaction(self, table: BankTransactionTable) -> BankTransaction:
        return BankTransaction(
            transaction_id=table.id,
            legal_entity_id=table.legal_entity_id,
            transaction_number=table.transaction_number,
            bank_account_id=table.bank_account_id,
            transaction_date=table.transaction_date,
            transaction_type=BankTransactionType(table.transaction_type),
            amount=table.amount,
            description=table.description,
            reference_number=table.reference_number,
            counterparty_account=table.counterparty_account,
            counterparty_name=table.counterparty_name,
            journal_id=table.journal_id,
            status=BankTransactionStatus(table.status),
            is_reconciled=table.is_reconciled,
            reconciliation_id=table.reconciliation_id,
            created_at=table.created_at,
            created_by=table.created_by,
            updated_at=table.updated_at,
            version=table.version,
            deleted_at=table.deleted_at,
            reconciled_at=None,
        )

    async def _to_orm_transaction(self, transaction: BankTransaction) -> BankTransactionTable:
        type_str = (
            transaction.transaction_type.value
            if hasattr(transaction.transaction_type, "value")
            else str(transaction.transaction_type)
        )
        status_str = (
            transaction.status.value if hasattr(transaction.status, "value") else str(transaction.status)
        )

        return BankTransactionTable(
            id=transaction.transaction_id,
            legal_entity_id=transaction.legal_entity_id,
            transaction_number=transaction.transaction_number,
            bank_account_id=transaction.bank_account_id,
            transaction_date=transaction.transaction_date,
            transaction_type=type_str,
            amount=transaction.amount,
            currency_code="IDR",
            description=transaction.description,
            reference_number=transaction.reference_number,
            counterparty_account=transaction.counterparty_account,
            counterparty_name=transaction.counterparty_name,
            journal_id=transaction.journal_id,
            status=status_str,
            is_reconciled=transaction.is_reconciled,
            reconciliation_id=transaction.reconciliation_id,
            created_at=transaction.created_at,
            created_by=transaction.created_by,
        )

    # ========================================================================
    # HELPER MAPPING METHODS - CASH BOOK
    # ========================================================================

    def _to_domain_cash_book(self, table: CashBookTable) -> CashBookRecord:
        return CashBookRecord(
            id=table.id,
            legal_entity_id=table.legal_entity_id,
            currency_code=table.currency_code,
            current_balance=table.current_balance,
            opening_balance=table.opening_balance,
            opening_balance_date=table.opening_balance_date,
            gl_cash_account_id=table.gl_cash_account_id,
            gl_bank_account_id=table.gl_bank_account_id,
            last_updated=table.last_updated,
            created_at=table.created_at,
            created_by=table.created_by,
            version=table.version,
        )

    # ========================================================================
    # BANK ACCOUNT METHODS (Implementasi Internal)
    # ========================================================================

    async def add_bank_account(self, account: BankAccountEntity) -> None:
        try:
            exists = await self.exists_by_account_number(
                account.account_number, account.legal_entity_id
            )
            if exists:
                raise DuplicateAccountNumberError(
                    f"Account number {account.account_number} already exists"
                )

            table = await self._to_orm_bank_account(account)
            self.session.add(table)
            await self.session.flush()
            logger.info("Bank account added: %s - %s", account.account_number, account.bank_name)

        except DuplicateAccountNumberError:
            raise
        except IntegrityError as e:
            await self.session.rollback()
            raise BankCashRepositoryError(f"Integrity error: {e}") from e
        except Exception as e:
            await self.session.rollback()
            raise BankCashRepositoryError(f"Failed to add bank account: {e}") from e

    async def get_bank_account_by_id(self, account_id: UUID) -> BankAccountEntity | None:
        try:
            stmt = select(BankAccountTable).where(
                BankAccountTable.id == account_id, BankAccountTable.deleted_at.is_(None)
            )
            result = await self.session.execute(stmt)
            table = result.scalar_one_or_none()
            if not table:
                return None
            return self._to_domain_bank_account(table)

        except Exception as e:
            raise BankCashRepositoryError(f"Failed to get bank account: {e}") from e

    async def get_bank_account_by_number(
        self, account_number: str, legal_entity_id: UUID
    ) -> BankAccountEntity | None:
        try:
            stmt = select(BankAccountTable).where(
                BankAccountTable.account_number == account_number,
                BankAccountTable.legal_entity_id == legal_entity_id,
                BankAccountTable.deleted_at.is_(None),
            )
            result = await self.session.execute(stmt)
            table = result.scalar_one_or_none()
            if not table:
                return None
            return self._to_domain_bank_account(table)

        except Exception as e:
            raise BankCashRepositoryError(f"Failed to get bank account: {e}") from e

    async def update_bank_account(self, account: BankAccountEntity) -> None:
        try:
            stmt = select(BankAccountTable).where(BankAccountTable.id == account.account_id)
            result = await self.session.execute(stmt)
            table = result.scalar_one_or_none()

            if table is None:
                raise BankAccountNotFoundError(f"Bank account {account.account_id} not found")

            if table.version != account.version:
                raise OptimisticLockError(
                    f"Version mismatch: expected {account.version}, got {table.version}"
                )

            status_str = (
                account.status.value if hasattr(account.status, "value") else str(account.status)
            )
            account_type_str = (
                account.account_type.value if hasattr(account.account_type, "value") else str(account.account_type)
            )

            # Update field pada objek yang SUDAH ter-attach ke session (bukan
            # objek baru yang di-merge). Version TIDAK disentuh manual di sini
            # -- `version_id_col` dari VersionMixin akan otomatis menaikkan
            # nilainya sendiri saat flush, dan otomatis melempar StaleDataError
            # kalau ada concurrent update. Menaikkan versi manual + merge()
            # (kode lama) bentrok dengan mekanisme otomatis ini, menyebabkan
            # "Version id 'X' on merged state does not match existing version".
            table.account_number = account.account_number
            table.bank_name = account.bank_name
            table.bank_code = account.bank_code
            table.account_name = account.account_name
            table.currency_code = account.currency
            table.account_type = account_type_str
            table.current_balance = account.current_balance
            table.available_balance = account.available_balance
            table.gl_account_id = account.gl_account_id
            table.is_active = account.is_active
            table.is_default = account.is_default
            table.status = status_str
            table.opening_balance = account.opening_balance
            table.opening_balance_date = account.opening_balance_date
            table.last_reconciliation_date = account.last_reconciled_date
            table.updated_at = datetime.utcnow()

            await self.session.flush()
            logger.info("Bank account updated: %s", account.account_number)

        except (OptimisticLockError, BankAccountNotFoundError):
            raise
        except Exception as e:
            await self.session.rollback()
            raise BankCashRepositoryError(f"Failed to update bank account: {e}") from e

    async def delete_bank_account(self, account_id: UUID) -> bool:
        try:
            stmt = (
                update(BankAccountTable)
                .where(BankAccountTable.id == account_id)
                .values(deleted_at=datetime.utcnow(), is_active=False, status="closed")
            )
            result = await self.session.execute(stmt)
            await self.session.flush()
            return result.rowcount > 0

        except Exception as e:
            await self.session.rollback()
            raise BankCashRepositoryError(f"Failed to delete bank account: {e}") from e

    async def list_bank_accounts(
        self, legal_entity_id: UUID, is_active: bool | None = True
    ) -> list[BankAccountEntity]:
        try:
            conditions = [
                BankAccountTable.legal_entity_id == legal_entity_id,
                BankAccountTable.deleted_at.is_(None),
            ]
            if is_active is not None:
                conditions.append(BankAccountTable.is_active == is_active)

            stmt = (
                select(BankAccountTable)
                .where(and_(*conditions))
                .order_by(BankAccountTable.account_number)
            )
            result = await self.session.execute(stmt)
            tables = result.scalars().all()
            return [self._to_domain_bank_account(table) for table in tables]

        except Exception as e:
            raise BankCashRepositoryError(f"Failed to list bank accounts: {e}") from e

    async def update_bank_balance(
        self, account_id: UUID, new_balance: Decimal, new_available_balance: Decimal, version: int
    ) -> None:
        try:
            stmt = (
                update(BankAccountTable)
                .where(BankAccountTable.id == account_id, BankAccountTable.version == version)
                .values(
                    current_balance=new_balance,
                    available_balance=new_available_balance,
                    version=version + 1,
                    updated_at=datetime.utcnow(),
                )
            )
            result = await self.session.execute(stmt)

            if result.rowcount == 0:
                raise OptimisticLockError(f"Failed to update balance for account {account_id}")

            await self.session.flush()

        except OptimisticLockError:
            raise
        except Exception as e:
            await self.session.rollback()
            raise BankCashRepositoryError(f"Failed to update balance: {e}") from e

    async def exists_by_account_number(self, account_number: str, legal_entity_id: UUID) -> bool:
        try:
            stmt = (
                select(func.count())
                .select_from(BankAccountTable)
                .where(
                    BankAccountTable.account_number == account_number,
                    BankAccountTable.legal_entity_id == legal_entity_id,
                    BankAccountTable.deleted_at.is_(None),
                )
            )
            result = await self.session.execute(stmt)
            count = result.scalar()
            return count > 0

        except Exception as e:
            raise BankCashRepositoryError(f"Failed to check account number: {e}") from e

    # ========================================================================
    # BANK TRANSACTION METHODS (Implementasi Internal)
    # ========================================================================

    async def add_bank_transaction(self, transaction: BankTransaction) -> None:
        try:
            table = await self._to_orm_transaction(transaction)
            self.session.add(table)
            await self.session.flush()
            logger.info("Bank transaction added: %s", transaction.transaction_number)

        except Exception as e:
            await self.session.rollback()
            raise BankCashRepositoryError(f"Failed to add bank transaction: {e}") from e

    async def get_bank_transaction_by_id(self, transaction_id: UUID) -> BankTransaction | None:
        try:
            stmt = select(BankTransactionTable).where(BankTransactionTable.id == transaction_id)
            result = await self.session.execute(stmt)
            table = result.scalar_one_or_none()
            if not table:
                return None
            return self._to_domain_transaction(table)

        except Exception as e:
            raise BankCashRepositoryError(f"Failed to get transaction: {e}") from e

    async def get_bank_transactions_by_account(
        self,
        bank_account_id: UUID,
        start_date: date | None = None,
        end_date: date | None = None,
        is_reconciled: bool | None = None,
        limit: int = 100,
    ) -> list[BankTransaction]:
        try:
            conditions = [BankTransactionTable.bank_account_id == bank_account_id]
            if start_date:
                conditions.append(BankTransactionTable.transaction_date >= start_date)
            if end_date:
                conditions.append(BankTransactionTable.transaction_date <= end_date)
            if is_reconciled is not None:
                conditions.append(BankTransactionTable.is_reconciled == is_reconciled)

            stmt = (
                select(BankTransactionTable)
                .where(and_(*conditions))
                .order_by(BankTransactionTable.transaction_date)
                .limit(limit)
            )

            result = await self.session.execute(stmt)
            tables = result.scalars().all()
            return [self._to_domain_transaction(table) for table in tables]

        except Exception as e:
            raise BankCashRepositoryError(f"Failed to get transactions: {e}") from e

    async def list_transactions_by_legal_entity(
        self,
        legal_entity_id: UUID,
        bank_account_id: UUID | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        transaction_type: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[BankTransaction]:
        try:
            conditions = [BankTransactionTable.legal_entity_id == legal_entity_id]
            if bank_account_id:
                conditions.append(BankTransactionTable.bank_account_id == bank_account_id)
            if start_date:
                conditions.append(BankTransactionTable.transaction_date >= start_date)
            if end_date:
                conditions.append(BankTransactionTable.transaction_date <= end_date)
            if transaction_type:
                conditions.append(BankTransactionTable.transaction_type == transaction_type)
            if status:
                conditions.append(BankTransactionTable.status == status)

            stmt = (
                select(BankTransactionTable)
                .where(and_(*conditions))
                .order_by(BankTransactionTable.transaction_date.desc())
                .offset(offset)
                .limit(limit)
            )

            result = await self.session.execute(stmt)
            tables = result.scalars().all()
            return [self._to_domain_transaction(table) for table in tables]

        except Exception as e:
            raise BankCashRepositoryError(f"Failed to list transactions: {e}") from e

    async def list_unreconciled_transactions(
        self, bank_account_id: UUID, as_of_date: date
    ) -> list[BankTransaction]:
        """FIX: dipakai oleh BankCashService.reconcile_bank_account() untuk
        mengambil transaksi yang belum direkonsiliasi sampai tanggal
        statement - method ini sebelumnya TIDAK ADA SAMA SEKALI, membuat
        endpoint reconcile selalu gagal 500 AttributeError."""
        try:
            stmt = (
                select(BankTransactionTable)
                .where(
                    BankTransactionTable.bank_account_id == bank_account_id,
                    BankTransactionTable.is_reconciled.is_(False),
                    BankTransactionTable.transaction_date <= as_of_date,
                    BankTransactionTable.deleted_at.is_(None),
                )
                .order_by(BankTransactionTable.transaction_date.asc())
            )
            result = await self.session.execute(stmt)
            tables = result.scalars().all()
            return [self._to_domain_transaction(table) for table in tables]
        except Exception as e:
            raise BankCashRepositoryError(f"Failed to list unreconciled transactions: {e}") from e

    async def save_transaction(self, transaction: BankTransaction) -> None:
        """FIX: dipakai oleh BankCashService.reconcile_bank_account() untuk
        menyimpan perubahan status is_reconciled/reconciled_at pada
        transaksi yang match - method ini sebelumnya TIDAK ADA SAMA
        SEKALI (mark_transaction_as_reconciled yang sudah ada butuh
        reconciliation_id yang belum tentu sudah dibuat di titik ini)."""
        try:
            stmt = (
                update(BankTransactionTable)
                .where(BankTransactionTable.id == transaction.transaction_id)
                .values(
                    is_reconciled=transaction.is_reconciled,
                    updated_at=datetime.utcnow(),
                )
            )
            await self.session.execute(stmt)
            await self.session.flush()
        except Exception as e:
            raise BankCashRepositoryError(f"Failed to save transaction: {e}") from e

    async def get_balance_before_date(self, bank_account_id: UUID, as_of_date: date) -> Decimal:
        try:
            stmt = select(
                func.coalesce(
                    func.sum(
                        case(
                            (
                                BankTransactionTable.transaction_type.in_(
                                    ["deposit", "transfer_in"]
                                ),
                                BankTransactionTable.amount,
                            ),
                            else_=-BankTransactionTable.amount,
                        )
                    ),
                    0,
                )
            ).where(
                BankTransactionTable.bank_account_id == bank_account_id,
                BankTransactionTable.transaction_date < as_of_date,
                BankTransactionTable.status == "posted",
            )

            result = await self.session.execute(stmt)
            balance = result.scalar() or 0

            account_stmt = select(BankAccountTable.opening_balance).where(
                BankAccountTable.id == bank_account_id
            )
            account_result = await self.session.execute(account_stmt)
            opening_balance = account_result.scalar() or 0

            return Decimal(str(opening_balance)) + Decimal(str(balance))

        except Exception as e:
            raise BankCashRepositoryError(f"Failed to get balance: {e}") from e

    async def mark_transaction_as_reconciled(
        self, transaction_id: UUID, reconciliation_id: UUID
    ) -> None:
        try:
            stmt = (
                update(BankTransactionTable)
                .where(BankTransactionTable.id == transaction_id)
                .values(
                    is_reconciled=True,
                    reconciliation_id=reconciliation_id,
                    updated_at=datetime.utcnow(),
                )
            )
            await self.session.execute(stmt)
            await self.session.flush()

        except Exception as e:
            raise BankCashRepositoryError(f"Failed to mark transaction: {e}") from e

    async def update_bank_transaction_fields(
        self,
        transaction_id: UUID,
        description: str | None = None,
        reference_number: str | None = None,
        status: str | None = None,
    ) -> None:
        """Update sebagian field non-kritis pada satu baris bank_transaction.

        FIX: dipakai oleh BankCashService.update_transaction(), yang
        sebelumnya tidak ada sama sekali di service layer padahal
        endpoint PUT /bank-cash/bank-cash/transactions/{id} sudah lama
        memanggilnya (selalu gagal 500 AttributeError). Sengaja hanya
        mendukung field non-kritis (description, reference_number,
        status) - amount/bank_account_id/transaction_type TIDAK bisa
        diubah lewat sini supaya jejak audit transaksi tetap utuh;
        koreksi nilai transaksi semestinya lewat reversal, bukan update
        langsung.
        """
        try:
            values = {"updated_at": datetime.utcnow()}
            if description is not None:
                values["description"] = description
            if reference_number is not None:
                values["reference_number"] = reference_number
            if status is not None:
                values["status"] = status

            stmt = (
                update(BankTransactionTable)
                .where(BankTransactionTable.id == transaction_id)
                .values(**values)
            )
            await self.session.execute(stmt)
            await self.session.flush()

        except Exception as e:
            raise BankCashRepositoryError(f"Failed to update transaction: {e}") from e

    # ========================================================================
    # BANK RECONCILIATION METHODS (Implementasi Internal)
    #
    # PENTING (fix menyeluruh): method-method di bawah ini SEBELUMNYA rusak
    # total dan tidak pernah benar-benar berfungsi:
    # - `add_reconciliation` (versi lama) membaca `reconciliation.book_balance`,
    #   `.matched_count`, `.unmatched_book`, dll dari objek `BankReconciliation`
    #   - padahal `BankReconciliation` cuma alias dari `ReconciliationResult`
    #   (domain/bank_cash/bank_reconciliation_engine.py) yang field-nya sama
    #   sekali berbeda (reconciliation_id, account_id, matched_items, dst),
    #   jadi akan langsung gagal AttributeError kalau sempat dipanggil.
    # - Lalu method itu MENULIS ke kolom `book_balance`, `matched_count`,
    #   `unmatched_book`, `unmatched_statement`, `adjustment_journal_id` di
    #   `BankReconciliationTable` - padahal kolom-kolom itu TIDAK ADA SAMA
    #   SEKALI di tabel (cek infrastructure/persistence_orm/
    #   bank_reconciliation_table.py: kolom asli yang ada adalah
    #   statement_ending_balance, system_ending_balance, difference, status,
    #   reconciled_by, reconciled_at, notes - beda total).
    # - `get_reconciliation_history` (versi lama) punya masalah SAMA PERSIS,
    #   membaca kolom yang tidak ada dari ORM row.
    # - `service_bank_cash.py` (reconcile_bank_account) memanggil
    #   `save_reconciliation(...)` yang bahkan TIDAK ADA SAMA SEKALI di
    #   sini sebelumnya.
    #
    # Statistik detail (matched_count, unmatched system/statement) TIDAK
    # punya kolom penyimpanan sendiri di tabel ini, jadi untuk sekarang
    # dirangkum sebagai teks singkat di kolom `notes` yang memang tersedia,
    # supaya informasi itu tidak hilang sama sekali walau tidak
    # ter-strukturkan penuh.
    # ========================================================================

    async def save_reconciliation(
        self,
        id: UUID,
        bank_account_id: UUID,
        statement_date: date,
        statement_balance: Decimal,
        system_balance: Decimal,
        difference: Decimal,
        is_matched: bool,
        matched_count: int,
        reconciliation_date: datetime,
        reconciled_by: UUID | None,
        unmatched_system_count: int = 0,
        unmatched_statement_count: int = 0,
        notes: str | None = None,
    ) -> UUID:
        try:
            bank_account = await self.get_bank_account_by_id(bank_account_id)
            legal_entity_id = bank_account.bank_account.legal_entity_id if bank_account else None

            period_start = statement_date.replace(day=1)
            summary = (
                f"matched={matched_count}; "
                f"unmatched_system={unmatched_system_count}; "
                f"unmatched_statement={unmatched_statement_count}"
            )
            full_notes = f"{notes.strip()} | {summary}" if notes and notes.strip() else summary

            table = BankReconciliationTable(
                id=id,
                legal_entity_id=legal_entity_id,
                bank_account_id=bank_account_id,
                statement_date=statement_date,
                period_start=period_start,
                period_end=statement_date,
                statement_ending_balance=statement_balance,
                system_ending_balance=system_balance,
                difference=difference,
                status="reconciled" if is_matched else "pending",
                reconciled_by=reconciled_by,
                reconciled_at=reconciliation_date,
                notes=full_notes,
                created_by=reconciled_by,
            )
            self.session.add(table)
            await self.session.flush()

            stmt = (
                update(BankAccountTable)
                .where(BankAccountTable.id == bank_account_id)
                .values(
                    last_reconciliation_date=statement_date,
                    updated_at=datetime.utcnow(),
                )
            )
            await self.session.execute(stmt)
            await self.session.flush()

            logger.info("Bank reconciliation saved for account %s", bank_account_id)
            return id

        except Exception as e:
            raise BankCashRepositoryError(f"Failed to save reconciliation: {e}") from e

    async def get_reconciliation_history(
        self, bank_account_id: UUID, limit: int = 12
    ) -> list[dict]:
        """Mengembalikan list of dict (bukan objek domain) - lebih sederhana
        dan jujur soal data apa yang benar-benar tersimpan di tabel ini,
        dibanding memaksakan ke dataclass domain yang field-nya tidak
        cocok sama sekali (lihat catatan panjang di atas)."""
        try:
            stmt = (
                select(BankReconciliationTable)
                .where(BankReconciliationTable.bank_account_id == bank_account_id)
                .order_by(BankReconciliationTable.statement_date.desc())
                .limit(limit)
            )
            result = await self.session.execute(stmt)
            tables = result.scalars().all()

            return [
                {
                    "id": t.id,
                    "bank_account_id": t.bank_account_id,
                    "statement_date": t.statement_date,
                    "statement_balance": t.statement_ending_balance,
                    "book_balance": t.system_ending_balance,
                    "difference": t.difference,
                    "status": t.status,
                    "notes": t.notes,
                    "reconciled_by": t.reconciled_by,
                    "reconciled_at": t.reconciled_at,
                    "created_by": t.created_by,
                    "created_at": t.created_at,
                }
                for t in tables
            ]
        except Exception as e:
            raise BankCashRepositoryError(f"Failed to get history: {e}") from e

    # ========================================================================
    # CASH BOOK METHODS (Implementasi Internal)
    # ========================================================================

    async def add_cash_book(self, cash_book: CashBookRecord) -> UUID:
        try:
            table = CashBookTable(
                id=cash_book.id,
                legal_entity_id=cash_book.legal_entity_id,
                currency_code=cash_book.currency_code,
                current_balance=cash_book.current_balance,
                opening_balance=cash_book.opening_balance,
                opening_balance_date=cash_book.opening_balance_date,
                gl_cash_account_id=cash_book.gl_cash_account_id,
                gl_bank_account_id=cash_book.gl_bank_account_id,
                last_updated=datetime.utcnow(),
                created_at=datetime.utcnow(),
                created_by=cash_book.created_by,
                version=1,
            )
            self.session.add(table)
            await self.session.flush()
            logger.info("Cash book added for legal entity %s", cash_book.legal_entity_id)
            return cash_book.id

        except Exception as e:
            await self.session.rollback()
            raise BankCashRepositoryError(f"Failed to add cash book: {e}") from e

    async def get_cash_book_by_id(self, cash_book_id: UUID) -> CashBookRecord | None:
        try:
            stmt = select(CashBookTable).where(CashBookTable.id == cash_book_id)
            result = await self.session.execute(stmt)
            table = result.scalar_one_or_none()
            if not table:
                return None
            return self._to_domain_cash_book(table)
        except Exception as e:
            raise BankCashRepositoryError(f"Failed to get cash book: {e}") from e

    async def list_cash_books_by_legal_entity(self, legal_entity_id: UUID) -> list[CashBookRecord]:
        try:
            stmt = select(CashBookTable).where(CashBookTable.legal_entity_id == legal_entity_id)
            result = await self.session.execute(stmt)
            tables = result.scalars().all()
            return [self._to_domain_cash_book(table) for table in tables]
        except Exception as e:
            raise BankCashRepositoryError(f"Failed to list cash books: {e}") from e

    async def update_cash_book(self, cash_book: CashBookRecord) -> None:
        try:
            stmt = select(CashBookTable).where(CashBookTable.id == cash_book.id)
            result = await self.session.execute(stmt)
            table = result.scalar_one_or_none()
            if table is None:
                raise CashBookNotFoundError(f"Cash book {cash_book.id} not found")
            if table.version != cash_book.version:
                raise OptimisticLockError(
                    f"Version mismatch: expected {cash_book.version}, got {table.version}"
                )

            table.gl_cash_account_id = cash_book.gl_cash_account_id
            table.gl_bank_account_id = cash_book.gl_bank_account_id
            table.last_updated = datetime.utcnow()
            # version TIDAK disentuh manual -- version_id_col yang urus otomatis.

            await self.session.flush()
            logger.info("Cash book updated: %s", cash_book.id)
        except (OptimisticLockError, CashBookNotFoundError):
            raise
        except Exception as e:
            await self.session.rollback()
            raise BankCashRepositoryError(f"Failed to update cash book: {e}") from e

    async def get_cash_book(
        self, legal_entity_id: UUID, currency_code: str = DEFAULT_CURRENCY
    ) -> CashBookRecord | None:
        try:
            stmt = select(CashBookTable).where(
                CashBookTable.legal_entity_id == legal_entity_id,
                CashBookTable.currency_code == currency_code,
            )
            result = await self.session.execute(stmt)
            table = result.scalar_one_or_none()
            if not table:
                return None
            return self._to_domain_cash_book(table)

        except Exception as e:
            raise BankCashRepositoryError(f"Failed to get cash book: {e}") from e

    async def update_cash_balance(
        self, cash_book_id: UUID, new_balance: Decimal, version: int
    ) -> None:
        try:
            stmt = (
                update(CashBookTable)
                .where(CashBookTable.id == cash_book_id, CashBookTable.version == version)
                .values(
                    current_balance=new_balance, version=version + 1, last_updated=datetime.utcnow()
                )
            )
            result = await self.session.execute(stmt)

            if result.rowcount == 0:
                raise OptimisticLockError(f"Failed to update cash balance for {cash_book_id}")

            await self.session.flush()

        except OptimisticLockError:
            raise
        except Exception as e:
            await self.session.rollback()
            raise BankCashRepositoryError(f"Failed to update cash balance: {e}") from e

    # ========================================================================
    # PETTY CASH FUND METHODS (Implementasi Internal)
    # ========================================================================

    async def add_petty_cash_fund(self, fund: PettyCashFund) -> UUID:
        # PENTING (fix): sebelumnya membaca fund.current_balance.amount,
        # fund.initial_amount.amount, fund.reimbursement_threshold.amount
        # - mengasumsikan field itu objek Money (punya .amount), padahal
        # PettyCashFund (didefinisikan ulang di service_bank_cash.py)
        # menyimpannya sebagai Decimal polos (karena service memakainya
        # langsung dengan operator +=/-= yang butuh Decimal polos, bukan
        # value object). Sekarang dibaca langsung tanpa .amount.
        try:
            table = PettyCashFundTable(
                id=fund.id,
                fund_name=fund.fund_name,
                legal_entity_id=fund.legal_entity_id,
                currency_code=fund.currency_code,
                current_balance=fund.current_balance,
                initial_amount=fund.initial_amount,
                custodian_id=fund.custodian_id,
                gl_account_id=fund.gl_account_id,
                reimbursement_threshold=fund.reimbursement_threshold,
                fund_location=fund.fund_location,
                status=fund.status,
                created_at=datetime.utcnow(),
                created_by=fund.created_by,
                version=1,
            )
            self.session.add(table)
            await self.session.flush()
            logger.info("Petty cash fund added: %s", fund.fund_name)
            return fund.id

        except Exception as e:
            await self.session.rollback()
            raise BankCashRepositoryError(f"Failed to add petty cash fund: {e}") from e

    def _petty_cash_table_to_domain(self, table) -> PettyCashFund:
        return PettyCashFund(
            id=table.id,
            fund_name=table.fund_name,
            legal_entity_id=table.legal_entity_id,
            currency_code=table.currency_code,
            current_balance=table.current_balance,
            initial_amount=table.initial_amount,
            custodian_id=table.custodian_id,
            gl_account_id=table.gl_account_id,
            reimbursement_threshold=table.reimbursement_threshold,
            fund_location=table.fund_location,
            status=table.status,
            is_active=(table.status == "active"),
            is_closed=(table.status == "closed"),
            created_by=table.created_by,
            created_at=table.created_at,
            updated_at=table.updated_at,
            version=table.version,
        )

    async def get_petty_cash_fund_by_id(self, fund_id: UUID) -> PettyCashFund | None:
        """FIX: method ini sebelumnya TIDAK ADA SAMA SEKALI, padahal
        dipanggil oleh hampir semua operasi petty cash di service
        (adjust/activate/close/suspend/disbursement/replenish) - semuanya
        selalu gagal AttributeError sebelum sempat melakukan apapun."""
        try:
            stmt = select(PettyCashFundTable).where(
                PettyCashFundTable.id == fund_id, PettyCashFundTable.deleted_at.is_(None)
            )
            result = await self.session.execute(stmt)
            table = result.scalar_one_or_none()
            return self._petty_cash_table_to_domain(table) if table else None
        except Exception as e:
            raise BankCashRepositoryError(f"Failed to get petty cash fund: {e}") from e

    async def save_petty_cash_fund(self, fund: PettyCashFund) -> None:
        """FIX: dipanggil oleh SEMUA operasi tulis petty cash di service
        (create/adjust/activate/close/suspend/disbursement/replenish),
        padahal method ini sebelumnya TIDAK ADA SAMA SEKALI. Berperilaku
        sebagai upsert: insert kalau ID belum ada, update kalau sudah."""
        try:
            stmt = select(PettyCashFundTable).where(PettyCashFundTable.id == fund.id)
            result = await self.session.execute(stmt)
            table = result.scalar_one_or_none()

            if table is None:
                await self.add_petty_cash_fund(fund)
                return

            table.fund_name = fund.fund_name
            table.currency_code = fund.currency_code
            table.current_balance = fund.current_balance
            table.initial_amount = fund.initial_amount
            table.custodian_id = fund.custodian_id
            table.gl_account_id = fund.gl_account_id
            table.reimbursement_threshold = fund.reimbursement_threshold
            table.fund_location = fund.fund_location
            table.status = fund.status
            table.updated_at = datetime.utcnow()
            table.version = (table.version or 1) + 1
            await self.session.flush()

        except Exception as e:
            raise BankCashRepositoryError(f"Failed to save petty cash fund: {e}") from e

    async def get_petty_cash_funds(self, legal_entity_id: UUID) -> list[PettyCashFund]:
        try:
            stmt = select(PettyCashFundTable).where(
                PettyCashFundTable.legal_entity_id == legal_entity_id,
                PettyCashFundTable.deleted_at.is_(None),
            )
            result = await self.session.execute(stmt)
            tables = result.scalars().all()
            return [self._petty_cash_table_to_domain(table) for table in tables]

        except Exception as e:
            raise BankCashRepositoryError(f"Failed to get petty cash funds: {e}") from e

    async def update_petty_cash_balance(
        self, fund_id: UUID, new_balance: Decimal, version: int
    ) -> None:
        try:
            stmt = (
                update(PettyCashFundTable)
                .where(PettyCashFundTable.id == fund_id, PettyCashFundTable.version == version)
                .values(
                    current_balance=new_balance, version=version + 1, updated_at=datetime.utcnow()
                )
            )
            result = await self.session.execute(stmt)

            if result.rowcount == 0:
                raise OptimisticLockError(f"Failed to update petty cash balance for {fund_id}")

            await self.session.flush()

        except OptimisticLockError:
            raise
        except Exception as e:
            await self.session.rollback()
            raise BankCashRepositoryError(f"Failed to update balance: {e}") from e

    # ========================================================================
    # GENERATE TRANSACTION NUMBER
    # ========================================================================

    async def get_next_transaction_number(self, prefix: str = "TRX", year: int = None) -> str:
        if year is None:
            year = date.today().year

        try:
            pattern = func.concat(prefix, '-', year, '-%')
            stmt = (
                select(BankTransactionTable.transaction_number)
                .where(BankTransactionTable.transaction_number.like(pattern))
                .order_by(BankTransactionTable.transaction_number.desc())
                .limit(1)
            )

            result = await self.session.execute(stmt)
            last_number = result.scalar_one_or_none()

            if last_number:
                seq = int(last_number.split("-")[-1]) + 1
            else:
                seq = 1

            return f"{prefix}-{year}-{seq:06d}"

        except Exception as e:
            raise BankCashRepositoryError(f"Failed to generate number: {e}") from e

    # ========================================================================
    # FORWARDING METHODS UNTUK BANKACCOUNTREPOSITORYPORT (INTERFACE)
    # ========================================================================

    async def add(self, bank_account: BankAccountEntity) -> None:
        """Forward ke add_bank_account."""
        await self.add_bank_account(bank_account)

    async def get_by_id(self, account_id: UUID) -> BankAccountEntity | None:
        """Forward ke get_bank_account_by_id."""
        return await self.get_bank_account_by_id(account_id)

    async def get_by_account_number(self, account_number: str, bank_code: str) -> BankAccountEntity | None:
        """Forward ke get_bank_account_by_number dengan bank_code."""
        try:
            stmt = select(BankAccountTable).where(
                BankAccountTable.account_number == account_number,
                BankAccountTable.bank_code == bank_code,
                BankAccountTable.deleted_at.is_(None),
            )
            result = await self.session.execute(stmt)
            table = result.scalar_one_or_none()
            if not table:
                return None
            return self._to_domain_bank_account(table)
        except Exception as e:
            logger.error("Failed to get bank account by number: %s", e)
            return None

    async def update(self, bank_account: BankAccountEntity) -> None:
        """Forward ke update_bank_account."""
        await self.update_bank_account(bank_account)

    async def delete(self, account_id: UUID, user_id: UUID, permanent: bool = False) -> bool:
        """Forward ke delete_bank_account."""
        return await self.delete_bank_account(account_id)

    async def find_by_legal_entity(self, legal_entity_id: UUID) -> list[BankAccountEntity]:
        """Forward ke list_bank_accounts."""
        return await self.list_bank_accounts(legal_entity_id)

    async def get_balance(self, bank_account_id: UUID, as_of_date: date) -> Decimal:
        """Forward ke get_balance_before_date."""
        return await self.get_balance_before_date(bank_account_id, as_of_date)

    async def record_transaction(self, transaction: BankTransaction) -> None:
        """Forward ke add_bank_transaction."""
        await self.add_bank_transaction(transaction)

    async def get_transactions(
        self, bank_account_id: UUID, start_date: date, end_date: date
    ) -> list[BankTransaction]:
        """Forward ke get_bank_transactions_by_account."""
        return await self.get_bank_transactions_by_account(
            bank_account_id, start_date, end_date, limit=1000
        )

    async def reconcile(
        self,
        bank_account_id: UUID,
        statement_date: date,
        statement_balance: Decimal,
        user_id: UUID,
        journal_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Forward ke add_reconciliation dengan return dict."""
        reconciliation = BankReconciliation(
            id=uuid4(),
            bank_account_id=bank_account_id,
            statement_date=statement_date,
            book_balance=Money(amount=Decimal(0), currency=DEFAULT_CURRENCY),
            statement_balance=Money(amount=statement_balance, currency=DEFAULT_CURRENCY),
            difference=Money(amount=Decimal(0), currency=DEFAULT_CURRENCY),
            matched_count=0,
            unmatched_book=[],
            unmatched_statement=[],
            adjustment_journal_id=journal_id,
            status="completed",
            created_by=user_id,
            created_at=datetime.utcnow(),
        )
        reconciliation_id = await self.add_reconciliation(reconciliation)
        return {
            "account_id": str(bank_account_id),
            "statement_date": statement_date.isoformat(),
            "statement_balance": float(statement_balance),
            "system_balance": 0.0,
            "difference": 0.0,
            "transactions_reconciled": 0,
            "reconciliation_id": str(reconciliation_id),
        }

    async def get_statistics(self, legal_entity_id: UUID) -> dict[str, Any]:
        """Get statistics untuk bank account."""
        accounts = await self.list_bank_accounts(legal_entity_id)
        total_balance = sum(acc.current_balance.amount for acc in accounts)
        return {
            "total_accounts": len(accounts),
            "total_balance": float(total_balance),
            "active_accounts": sum(1 for acc in accounts if acc.is_active),
            "by_currency": {},
            "by_type": {},
        }


# ============================================================================
# ALIAS FOR BACKWARD COMPATIBILITY
# ============================================================================

SQLAlchemyBankCashRepository = SQLAlchemyBankAccountRepository
SqlAlchemyBankCashRepository = SQLAlchemyBankAccountRepository


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "BankAccountNotFoundError",
    "BankCashRepositoryError",
    "CashBookNotFoundError",
    "DuplicateAccountNumberError",
    "InsufficientBalanceError",
    "OptimisticLockError",
    "ReconciliationNotFoundError",
    "SQLAlchemyBankAccountRepository",
    "SQLAlchemyBankCashRepository",
    "SqlAlchemyBankCashRepository",
]
