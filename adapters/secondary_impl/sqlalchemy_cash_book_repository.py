#!/usr/bin/env python3
"""
Module: sqlalchemy_cash_book_repository.py
Layer: Adapters (Secondary Implementation)
Responsibility: Implementasi CashBookRepositoryPort dengan SQLAlchemy.
Perbaikan:
  - Menghilangkan float() pada nilai moneter (diganti str()).
  - [FIX] Race condition pada update dan record_transaction dengan pessimistic locking.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Column, Date, DateTime, Index, Numeric, String, Text, func, select
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import declarative_base

from ports.primary.bank_cash_repository_port import (
    CashBook,
    CashBookRepositoryPort,
    CashTransaction,
)

Base = declarative_base()


class CashBookTable(Base):
    __tablename__ = "cash_books"
    __table_args__ = (
        Index("idx_cashbook_legal_entity", "legal_entity_id"),
        Index("idx_cashbook_type", "cash_type"),
    )

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    legal_entity_id = Column(PGUUID(as_uuid=True), nullable=False)
    cash_type = Column(String(50), nullable=False)  # MAIN_CASH, PETTY_CASH
    currency_code = Column(String(3), nullable=False, default="IDR")
    opening_balance = Column(Numeric(20, 2), nullable=False, default=0)
    current_balance = Column(Numeric(20, 2), nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=True, onupdate=datetime.utcnow)
    created_by = Column(PGUUID(as_uuid=True), nullable=True)
    updated_by = Column(PGUUID(as_uuid=True), nullable=True)


class CashTransactionTable(Base):
    __tablename__ = "cash_transactions"
    __table_args__ = (
        Index("idx_cashtx_cashbook", "cash_book_id"),
        Index("idx_cashtx_date", "transaction_date"),
        Index("idx_cashtx_reference", "reference_type", "reference_id"),
    )

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cash_book_id = Column(PGUUID(as_uuid=True), nullable=False)
    transaction_date = Column(Date, nullable=False)
    transaction_type = Column(String(20), nullable=False)  # CASH_IN, CASH_OUT
    amount = Column(Numeric(20, 2), nullable=False)
    description = Column(Text, nullable=True)
    reference_type = Column(String(50), nullable=True)
    reference_id = Column(PGUUID(as_uuid=True), nullable=True)
    journal_id = Column(PGUUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    created_by = Column(PGUUID(as_uuid=True), nullable=True)


class SQLAlchemyCashBookRepository(CashBookRepositoryPort):
    """
    Implementasi CashBookRepositoryPort dengan SQLAlchemy.
    """

    def __init__(self, session: AsyncSession | None = None):
        self._session = session
        self._audit_log: list[dict[str, Any]] = []

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            from infrastructure.database.session_factory_sqlalchemy import get_async_session
            self._session = await get_async_session()
        return self._session

    async def _log_audit(self, action: str, cash_book_id: uuid.UUID, user_id: uuid.UUID, details: dict[str, Any]) -> None:
        self._audit_log.append({
            "timestamp": datetime.utcnow().isoformat(),
            "action": action,
            "cash_book_id": str(cash_book_id),
            "user_id": str(user_id),
            "details": details,
        })

    async def add(self, cash_book: CashBook) -> None:
        session = await self._get_session()
        # Cek duplicate
        stmt = select(CashBookTable).where(CashBookTable.id == cash_book.id)
        result = await session.execute(stmt)
        if result.scalar_one_or_none():
            raise ValueError(f"CashBook {cash_book.id} already exists")

        new = CashBookTable(
            id=cash_book.id or uuid.uuid4(),
            legal_entity_id=cash_book.legal_entity_id,
            cash_type=cash_book.cash_type,
            currency_code=cash_book.currency_code,
            opening_balance=cash_book.opening_balance,
            current_balance=cash_book.current_balance,
            created_by=cash_book.created_by,
        )
        session.add(new)
        await session.commit()
        await self._log_audit("ADD", cash_book.id, cash_book.created_by, {"type": cash_book.cash_type})

    async def get_by_id(self, cash_book_id: uuid.UUID) -> CashBook | None:
        session = await self._get_session()
        stmt = select(CashBookTable).where(CashBookTable.id == cash_book_id)
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        return self._to_cash_book(row) if row else None

    async def get_by_legal_entity_and_currency(
        self, legal_entity_id: uuid.UUID, currency: str, cash_type: str = "MAIN_CASH"
    ) -> CashBook | None:
        session = await self._get_session()
        stmt = select(CashBookTable).where(
            CashBookTable.legal_entity_id == legal_entity_id,
            CashBookTable.currency_code == currency,
            CashBookTable.cash_type == cash_type,
        )
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        return self._to_cash_book(row) if row else None

    async def update(self, cash_book: CashBook) -> None:
        session = await self._get_session()
        async with session.begin():
            # Lock the row to prevent race conditions
            stmt = select(CashBookTable).where(CashBookTable.id == cash_book.id).with_for_update()
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()
            if not existing:
                raise ValueError(f"CashBook {cash_book.id} not found")

            existing.currency_code = cash_book.currency_code
            existing.cash_type = cash_book.cash_type
            existing.opening_balance = cash_book.opening_balance
            existing.current_balance = cash_book.current_balance
            existing.updated_at = datetime.utcnow()
            existing.updated_by = cash_book.updated_by
            await session.flush()
            # ✅ Gunakan str() bukan float()
            await self._log_audit("UPDATE", cash_book.id, cash_book.updated_by, {"balance": str(cash_book.current_balance)})

    async def record_transaction(
        self,
        cash_book_id: uuid.UUID,
        transaction_type: str,
        amount: Decimal,
        reference_type: str,
        reference_id: uuid.UUID,
        description: str,
        user_id: uuid.UUID,
        journal_id: uuid.UUID | None = None,
    ) -> CashTransaction:
        session = await self._get_session()
        async with session.begin():
            # Lock the cash book row to prevent race conditions on balance update
            stmt = select(CashBookTable).where(CashBookTable.id == cash_book_id).with_for_update()
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()
            if not existing:
                raise ValueError(f"CashBook {cash_book_id} not found")

            if transaction_type not in ("CASH_IN", "CASH_OUT"):
                raise ValueError("transaction_type must be CASH_IN or CASH_OUT")

            # Convert to Decimal for safe arithmetic
            current_balance = Decimal(str(existing.current_balance))
            amount_dec = Decimal(str(amount))

            if transaction_type == "CASH_OUT" and amount_dec > current_balance:
                raise ValueError("Insufficient cash balance")

            # Update balance
            if transaction_type == "CASH_IN":
                new_balance = current_balance + amount_dec
            else:
                new_balance = current_balance - amount_dec

            existing.current_balance = new_balance
            existing.updated_at = datetime.utcnow()
            existing.updated_by = user_id

            # Create transaction record
            tx = CashTransaction(
                id=uuid.uuid4(),
                cash_book_id=cash_book_id,
                transaction_date=date.today(),
                transaction_type=transaction_type,
                amount=amount_dec,
                description=description,
                reference_type=reference_type,
                reference_id=reference_id,
                journal_id=journal_id,
                created_by=user_id,
            )
            new_tx = CashTransactionTable(
                id=tx.id,
                cash_book_id=tx.cash_book_id,
                transaction_date=tx.transaction_date,
                transaction_type=tx.transaction_type,
                amount=tx.amount,
                description=tx.description,
                reference_type=tx.reference_type,
                reference_id=tx.reference_id,
                journal_id=tx.journal_id,
                created_by=tx.created_by,
            )
            session.add(new_tx)
            await session.flush()

            await self._log_audit(
                "RECORD_TX",
                cash_book_id,
                user_id,
                {"type": transaction_type, "amount": str(amount), "reference": reference_type},
            )
            return tx

    async def get_balance(self, cash_book_id: uuid.UUID, as_of_date: date) -> Decimal:
        session = await self._get_session()
        # Get opening balance
        cash_book = await self.get_by_id(cash_book_id)
        if not cash_book:
            raise ValueError(f"CashBook {cash_book_id} not found")
        balance = cash_book.opening_balance

        # Sum transactions up to as_of_date
        stmt = select(
            func.coalesce(func.sum(CashTransactionTable.amount), 0)
        ).where(
            CashTransactionTable.cash_book_id == cash_book_id,
            CashTransactionTable.transaction_date <= as_of_date,
            CashTransactionTable.transaction_type == "CASH_IN",
        )
        result = await session.execute(stmt)
        cash_in = Decimal(str(result.scalar() or 0))

        stmt = select(
            func.coalesce(func.sum(CashTransactionTable.amount), 0)
        ).where(
            CashTransactionTable.cash_book_id == cash_book_id,
            CashTransactionTable.transaction_date <= as_of_date,
            CashTransactionTable.transaction_type == "CASH_OUT",
        )
        result = await session.execute(stmt)
        cash_out = Decimal(str(result.scalar() or 0))

        return balance + cash_in - cash_out

    async def get_transactions(
        self, cash_book_id: uuid.UUID, start_date: date, end_date: date
    ) -> list[CashTransaction]:
        session = await self._get_session()
        stmt = select(CashTransactionTable).where(
            CashTransactionTable.cash_book_id == cash_book_id,
            CashTransactionTable.transaction_date >= start_date,
            CashTransactionTable.transaction_date <= end_date,
        ).order_by(CashTransactionTable.transaction_date)
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [self._to_cash_transaction(row) for row in rows]

    def _to_cash_book(self, row: CashBookTable) -> CashBook:
        return CashBook(
            id=row.id,
            legal_entity_id=row.legal_entity_id,
            cash_type=row.cash_type,
            currency_code=row.currency_code,
            opening_balance=Decimal(str(row.opening_balance)),
            current_balance=Decimal(str(row.current_balance)),
            created_at=row.created_at,
            updated_at=row.updated_at,
            created_by=row.created_by,
            updated_by=row.updated_by,
        )

    def _to_cash_transaction(self, row: CashTransactionTable) -> CashTransaction:
        return CashTransaction(
            id=row.id,
            cash_book_id=row.cash_book_id,
            transaction_date=row.transaction_date,
            transaction_type=row.transaction_type,
            amount=Decimal(str(row.amount)),
            description=row.description,
            reference_type=row.reference_type,
            reference_id=row.reference_id,
            journal_id=row.journal_id,
            created_at=row.created_at,
            created_by=row.created_by,
        )


__all__ = ["CashBookTable", "CashTransactionTable", "SQLAlchemyCashBookRepository"]