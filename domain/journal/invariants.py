#!/usr/bin/env python3
"""
Module: invariants.py
Layer: 6 - Domain / Journal
Responsibility: Aturan: Debit = Kredit, akun valid, periode terbuka.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from domain.coa.account_entity import AccountEntity
from domain.journal.journal_entity import JournalEntity, JournalStatus
from domain.journal.journal_line_vo import JournalLineVO, JournalSide
from domain.journal.state_machine import JournalStateMachine

logger = logging.getLogger(__name__)


class InvariantResult:
    def __init__(self, is_valid: bool = True, errors: list[str] | None = None):
        self.is_valid = is_valid
        self.errors = errors or []

    def add_error(self, error: str) -> None:
        self.errors.append(error)
        self.is_valid = False

    def merge(self, other: InvariantResult) -> InvariantResult:
        if not other.is_valid:
            self.is_valid = False
            self.errors.extend(other.errors)
        return self

    def __bool__(self) -> bool:
        return self.is_valid

    def __str__(self) -> str:
        if self.is_valid:
            return "InvariantResult: valid"
        return f"InvariantResult: invalid - {', '.join(self.errors)}"


class JournalInvariants:
    @staticmethod
    def validate_balance(
        total_debit: Decimal,
        total_credit: Decimal,
        tolerance: Decimal = Decimal("0.0001"),
    ) -> InvariantResult:
        result = InvariantResult(True)
        if abs(total_debit - total_credit) > tolerance:
            result.add_error(f"Journal is not balanced: debit={total_debit}, credit={total_credit}")
        return result

    @staticmethod
    def validate_lines_exist(lines: list[JournalLineVO]) -> InvariantResult:
        result = InvariantResult(True)
        if not lines or len(lines) == 0:
            result.add_error("Journal must have at least one line")
        return result

    @staticmethod
    def validate_line_amounts(lines: list[JournalLineVO]) -> InvariantResult:
        result = InvariantResult(True)
        for line in lines:
            if line.amount <= 0:
                result.add_error(f"Line {line.line_id} has invalid amount: {line.amount}")
            if line.amount > Decimal("9999999999999.99"):
                result.add_error(f"Line {line.line_id} amount exceeds maximum: {line.amount}")
        return result

    @staticmethod
    def validate_accounts_exist(
        lines: list[JournalLineVO],
        account_getter: Callable[[UUID], AccountEntity | None],
    ) -> InvariantResult:
        result = InvariantResult(True)
        for line in lines:
            account = account_getter(line.account_id)
            if not account:
                result.add_error(f"Account {line.account_id} not found")
            elif not getattr(account, "is_active", True):
                result.add_error(f"Account {line.account_code} is not active")
        return result

    @staticmethod
    def validate_legal_entity_consistency(
        lines: list[JournalLineVO],
        legal_entity_id: UUID,
    ) -> InvariantResult:
        result = InvariantResult(True)
        for line in lines:
            if line.legal_entity_id != legal_entity_id:
                result.add_error(
                    f"Line {line.line_id} has legal_entity_id {line.legal_entity_id}, "
                    f"but journal has {legal_entity_id}"
                )
        return result

    @staticmethod
    def validate_transaction_date(
        transaction_date: datetime,
        period_start: datetime | None = None,
        period_end: datetime | None = None,
        max_backdate_days: int = 30,
    ) -> InvariantResult:
        result = InvariantResult(True)
        now = datetime.now(UTC)

        if transaction_date > now:
            result.add_error(f"Transaction date {transaction_date.date()} cannot be in the future")

        if (now - transaction_date).days > max_backdate_days:
            result.add_error(
                f"Transaction date {transaction_date.date()} is {(now - transaction_date).days} days in the past, "
                f"exceeds limit of {max_backdate_days} days"
            )

        if period_start and transaction_date < period_start:
            result.add_error(f"Transaction date is before period start {period_start.date()}")

        if period_end and transaction_date > period_end:
            result.add_error(f"Transaction date is after period end {period_end.date()}")

        return result

    @staticmethod
    def validate_journal_number_unique(
        journal_number: str,
        existing_numbers: set[str],
    ) -> InvariantResult:
        result = InvariantResult(True)
        if journal_number in existing_numbers:
            result.add_error(f"Journal number {journal_number} already exists")
        if len(journal_number) > 50:
            result.add_error(f"Journal number {journal_number} exceeds maximum length of 50")
        return result

    @staticmethod
    def validate_status_transition(
        current_status: JournalStatus,
        new_status: JournalStatus,
        user_role: str,
        is_balanced: bool = True,
        period_is_open: bool = True,
    ) -> InvariantResult:
        result = InvariantResult(True)
        is_valid, message = JournalStateMachine.validate_transition(
            from_status=current_status,
            to_status=new_status,
            user_role=user_role,
            is_balanced=is_balanced,
            period_is_open=period_is_open,
        )
        if not is_valid:
            result.add_error(
                message or f"Invalid transition from {current_status.value} to {new_status.value}"
            )
        return result

    @staticmethod
    def validate_reversal_reference(
        reversal_of: UUID | None,
        original_journal_exists: bool = True,
        original_journal_is_posted: bool = True,
    ) -> InvariantResult:
        result = InvariantResult(True)
        if reversal_of and not original_journal_exists:
            result.add_error(f"Original journal {reversal_of} not found for reversal")
        if reversal_of and not original_journal_is_posted:
            result.add_error(f"Original journal {reversal_of} is not posted, cannot reverse")
        return result

    @staticmethod
    def validate_date_consistency(
        transaction_date: datetime,
        posting_date: datetime | None,
    ) -> InvariantResult:
        result = InvariantResult(True)
        if posting_date and posting_date < transaction_date:
            result.add_error(
                f"Posting date {posting_date.date()} cannot be before transaction date {transaction_date.date()}"
            )
        return result

    @staticmethod
    def validate_currency_consistency(lines: list[JournalLineVO]) -> InvariantResult:
        result = InvariantResult(True)
        if not lines:
            return result
        first_currency = getattr(lines[0], "currency", "IDR")
        for line in lines:
            currency = getattr(line, "currency", "IDR")
            if currency != first_currency:
                result.add_error(
                    f"Line {line.line_id} has currency {currency}, expected {first_currency}"
                )
        return result


class JournalInvariantEnforcer:
    def __init__(
        self,
        account_getter: Callable[[UUID], AccountEntity | None],
        journal_number_checker: Callable[[UUID], set[str]],
        period_checker: Callable[[UUID, datetime], tuple[datetime | None, datetime | None]],
    ):
        self._account_getter = account_getter
        self._journal_number_checker = journal_number_checker
        self._period_checker = period_checker
        self._invariants = JournalInvariants()

    async def enforce_create(
        self,
        journal: JournalEntity,
        lines: list[JournalLineVO],
    ) -> InvariantResult:
        result = InvariantResult(True)
        result.merge(self._invariants.validate_lines_exist(lines))
        result.merge(self._invariants.validate_line_amounts(lines))

        total_debit = sum((line.amount for line in lines if line.side == JournalSide.DEBIT), Decimal(0))
        total_credit = sum((line.amount for line in lines if line.side == JournalSide.CREDIT), Decimal(0))
        result.merge(self._invariants.validate_balance(total_debit, total_credit))
        result.merge(
            self._invariants.validate_legal_entity_consistency(lines, journal.legal_entity_id)
        )
        result.merge(self._invariants.validate_accounts_exist(lines, self._account_getter))
        result.merge(self._invariants.validate_currency_consistency(lines))

        # journal_number_checker is sync, no await
        existing_numbers = self._journal_number_checker(journal.legal_entity_id)
        result.merge(
            self._invariants.validate_journal_number_unique(
                journal.journal_number, existing_numbers
            )
        )

        # period_checker is sync, no await
        period_start, period_end = self._period_checker(
            journal.legal_entity_id, journal.transaction_date
        )
        result.merge(
            self._invariants.validate_transaction_date(
                journal.transaction_date, period_start, period_end
            )
        )

        # posting_date might not exist on JournalEntity; use getattr fallback None
        posting_date = getattr(journal, "posting_date", None)
        result.merge(
            self._invariants.validate_date_consistency(
                journal.transaction_date, posting_date
            )
        )

        return result

    async def enforce_status_transition(
        self,
        journal: JournalEntity,
        new_status: JournalStatus,
        user_role: str,
        is_balanced: bool = True,
        period_is_open: bool = True,
    ) -> InvariantResult:
        return self._invariants.validate_status_transition(
            journal.status, new_status, user_role, is_balanced, period_is_open
        )

    async def enforce_reversal(
        self,
        reversal_of: UUID,
        original_exists: bool,
        original_posted: bool,
    ) -> InvariantResult:
        return self._invariants.validate_reversal_reference(
            reversal_of, original_exists, original_posted
        )


class JournalInvariantsValidator:
    def __init__(self):
        self._invariants = JournalInvariants()

    def validate_balance(self, total_debit: Decimal, total_credit: Decimal) -> InvariantResult:
        return self._invariants.validate_balance(total_debit, total_credit)

    def validate_lines_exist(self, lines: list[Any]) -> InvariantResult:
        return self._invariants.validate_lines_exist(lines)

    def validate_line_amounts(self, lines: list[Any]) -> InvariantResult:
        return self._invariants.validate_line_amounts(lines)

    def validate_legal_entity_consistency(
        self, lines: list[Any], legal_entity_id: UUID
    ) -> InvariantResult:
        return self._invariants.validate_legal_entity_consistency(lines, legal_entity_id)

    def validate_transaction_date(
        self,
        transaction_date: datetime,
        period_start: datetime | None = None,
        period_end: datetime | None = None,
        max_backdate_days: int = 30,
    ) -> InvariantResult:
        return self._invariants.validate_transaction_date(
            transaction_date, period_start, period_end, max_backdate_days
        )

    def validate_accounts_exist(
        self, lines: list[Any], account_getter: Callable[[UUID], AccountEntity | None]
    ) -> InvariantResult:
        return self._invariants.validate_accounts_exist(lines, account_getter)

    def validate_journal_number_unique(
        self, journal_number: str, existing_numbers: set[str]
    ) -> InvariantResult:
        return self._invariants.validate_journal_number_unique(journal_number, existing_numbers)

    def validate_status_transition(
        self, current_status: JournalStatus, new_status: JournalStatus, user_role: str
    ) -> InvariantResult:
        return self._invariants.validate_status_transition(current_status, new_status, user_role)

    def validate_reversal_reference(
        self, reversal_of: UUID | None, original_journal_exists: bool = True
    ) -> InvariantResult:
        return self._invariants.validate_reversal_reference(reversal_of, original_journal_exists)

    def validate_currency_consistency(self, lines: list[Any]) -> InvariantResult:
        return self._invariants.validate_currency_consistency(lines)

    def validate_date_consistency(
        self, transaction_date: datetime, posting_date: datetime | None
    ) -> InvariantResult:
        return self._invariants.validate_date_consistency(transaction_date, posting_date)

    def validate_all(self, journal: JournalEntity, lines: list[Any]) -> InvariantResult:
        result = InvariantResult(True)
        result.merge(self.validate_lines_exist(lines))
        result.merge(self.validate_line_amounts(lines))
        total_debit = sum(
            (getattr(line, "amount", Decimal(0))
             for line in lines
             if getattr(line, "side", JournalSide.DEBIT) == JournalSide.DEBIT),
            Decimal(0)
        )
        total_credit = sum(
            (getattr(line, "amount", Decimal(0))
             for line in lines
             if getattr(line, "side", JournalSide.CREDIT) == JournalSide.CREDIT),
            Decimal(0)
        )
        result.merge(self.validate_balance(total_debit, total_credit))
        result.merge(self.validate_legal_entity_consistency(lines, journal.legal_entity_id))
        result.merge(self.validate_transaction_date(journal.transaction_date))
        result.merge(self.validate_currency_consistency(lines))

        # posting_date may not exist on JournalEntity
        posting_date = getattr(journal, "posting_date", None)
        result.merge(self.validate_date_consistency(journal.transaction_date, posting_date))
        return result


__all__ = [
    "InvariantResult",
    "JournalInvariantEnforcer",
    "JournalInvariants",
    "JournalInvariantsValidator",
]
