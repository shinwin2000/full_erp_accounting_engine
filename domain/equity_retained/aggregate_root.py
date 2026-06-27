#!/usr/bin/env python3
"""
Module: aggregate_root.py
Layer: Domain / Equity & Retained Earnings
Responsibility: Aggregate root untuk Equity management.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, ClassVar
from uuid import UUID, uuid4

from domain.equity_retained.capital_contribution_entity import (
    CapitalContributionEntity,
    ContributionStatus,
)
from domain.equity_retained.capital_withdrawal_entity import (
    CapitalWithdrawalEntity,
    WithdrawalStatus,
)
from domain.equity_retained.dividend_declaration_entity import (
    DividendDeclarationEntity,
    DividendStatus,
)
from domain.equity_retained.domain_events import (
    CapitalContributionApprovedEvent,
    CapitalContributionCancelledEvent,
    CapitalContributionPostedEvent,
    CapitalContributionRecordedEvent,
    CapitalWithdrawalApprovedEvent,
    CapitalWithdrawalCancelledEvent,
    CapitalWithdrawalPostedEvent,
    CapitalWithdrawalRecordedEvent,
    DividendApprovedEvent,
    DividendCancelledEvent,
    DividendDeclaredEvent,
    DividendPaidEvent,
    DividendPartiallyPaidEvent,
    DomainEvent,
    RetainedEarningsAdjustedEvent,
    RetainedEarningsUpdatedEvent,
)
from domain.equity_retained.retained_earnings_entity import (
    RetainedEarningsEntity,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Custom Exceptions
# ============================================================================


class EquityAggregateError(ValueError):
    pass


class InsufficientPaidInCapitalError(EquityAggregateError):
    pass


class InsufficientRetainedEarningsError(EquityAggregateError):
    pass


class DuplicateTransactionError(EquityAggregateError):
    pass


class TransactionNotFoundError(EquityAggregateError):
    pass


# ============================================================================
# Equity Aggregate Root
# ============================================================================


@dataclass
class EquityAggregate:
    equity_id: UUID
    legal_entity_id: UUID
    legal_entity_name: str
    capital_contributions: dict[UUID, CapitalContributionEntity] = field(default_factory=dict)
    capital_withdrawals: dict[UUID, CapitalWithdrawalEntity] = field(default_factory=dict)
    retained_earnings: RetainedEarningsEntity = field(
        default_factory=lambda: RetainedEarningsEntity.create(uuid4(), Decimal("0"))
    )
    dividend_declarations: list[DividendDeclarationEntity] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str = "system"
    version: int = 1

    _events: ClassVar[list[DomainEvent]] = []
    _audit_trail: ClassVar[list[dict[str, Any]]] = []
    _snapshots: ClassVar[list[dict[str, Any]]] = []

    def __post_init__(self) -> None:
        if not self.legal_entity_name or len(self.legal_entity_name.strip()) < 2:
            raise EquityAggregateError("Legal entity name must be at least 2 characters")
        if self.version < 1:
            raise EquityAggregateError("Version must be >= 1")
        self._take_snapshot()

    # ==================== PRIVATE HELPERS ====================

    def _take_snapshot(self) -> None:
        snapshot = {
            "version": self.version,
            "equity_id": str(self.equity_id),
            "legal_entity_name": self.legal_entity_name,
            "total_equity": str(self.total_equity),
            "timestamp": datetime.now(UTC).isoformat(),
        }
        self._snapshots.append(snapshot)
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]) -> None:
        entry = {
            "action": action,
            "performed_by": performed_by,
            "timestamp": datetime.now(UTC).isoformat(),
            "version": self.version,
            "equity_id": str(self.equity_id),
            "details": details,
        }
        self._audit_trail.append(entry)

    def _register_event(self, event: DomainEvent) -> None:
        self._events.append(event)

    # ==================== ENTITY DASAR METHODS (untuk aggregate) ====================

    def create(self, created_by: str) -> EquityAggregate:
        self._record_audit("CREATE", created_by, {"legal_entity_name": self.legal_entity_name})
        return self

    def update(self, updated_by: str, **kwargs) -> EquityAggregate:
        data = self.to_dict()
        for key, value in kwargs.items():
            if key not in ("equity_id", "created_at", "version"):
                data[key] = value
        new_agg = EquityAggregate(
            equity_id=self.equity_id,
            legal_entity_id=self.legal_entity_id,
            legal_entity_name=data.get("legal_entity_name", self.legal_entity_name),
            capital_contributions=self.capital_contributions,
            capital_withdrawals=self.capital_withdrawals,
            retained_earnings=self.retained_earnings,
            dividend_declarations=self.dividend_declarations,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=updated_by,
            version=self.version + 1,
        )
        new_agg._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new_agg

    def delete(self, deleted_by: str, reason: str | None = None) -> EquityAggregate:
        if self.total_equity != 0:
            raise EquityAggregateError(
                f"Cannot delete aggregate with non-zero equity: {self.total_equity}"
            )
        if len(self.capital_contributions) > 0 or len(self.capital_withdrawals) > 0:
            raise EquityAggregateError("Cannot delete aggregate with existing transactions")
        new_agg = self._copy()
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        new_agg._record_audit("DELETE", deleted_by, {"reason": reason})
        return new_agg

    def restore(self, restored_by: str) -> EquityAggregate:
        new_agg = self._copy()
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        new_agg._record_audit("RESTORE", restored_by, {})
        return new_agg

    def activate(self, activated_by: str) -> EquityAggregate:
        new_agg = self._copy()
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        new_agg._record_audit("ACTIVATE", activated_by, {})
        return new_agg

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> EquityAggregate:
        new_agg = self._copy()
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        new_agg._record_audit("DEACTIVATE", deactivated_by, {"reason": reason})
        return new_agg

    def lock(self, locked_by: str, reason: str) -> EquityAggregate:
        new_agg = self._copy()
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        new_agg._record_audit("LOCK", locked_by, {"reason": reason})
        return new_agg

    def unlock(self, unlocked_by: str) -> EquityAggregate:
        new_agg = self._copy()
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        new_agg._record_audit("UNLOCK", unlocked_by, {})
        return new_agg

    def validate(self) -> dict[str, Any]:
        errors = []
        # Validate contributions
        for contrib in self.capital_contributions.values():
            if contrib.amount < 0:
                errors.append(f"Contribution {contrib.contribution_number} has negative amount")
        # Validate withdrawals
        total_contrib = self.total_posted_contributions
        total_withdraw = self.total_posted_withdrawals
        if total_withdraw > total_contrib:
            errors.append(
                f"Total withdrawals {total_withdraw} exceed total contributions {total_contrib}"
            )
        # Validate dividends
        total_dividends = sum(
            d.total_amount for d in self.dividend_declarations if d.status == DividendStatus.PAID
        )
        if total_dividends > self.total_retained_earnings + self.total_paid_in_capital:
            errors.append(f"Total dividends {total_dividends} exceed available equity")
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "equity_id": str(self.equity_id),
            "version": self.version,
        }

    def to_dict(self, include_entries: bool = True) -> dict[str, Any]:
        return {
            "equity_id": str(self.equity_id),
            "legal_entity_id": str(self.legal_entity_id),
            "legal_entity_name": self.legal_entity_name,
            "capital_contributions": [c.to_dict() for c in self.capital_contributions.values()],
            "capital_withdrawals": [w.to_dict() for w in self.capital_withdrawals.values()],
            "retained_earnings": self.retained_earnings.to_dict(include_entries),
            "dividend_declarations": [d.to_dict() for d in self.dividend_declarations],
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "created_by": self.created_by,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EquityAggregate:
        contributions = {}
        for c_data in data.get("capital_contributions", []):
            c = CapitalContributionEntity.from_dict(c_data)
            contributions[c.contribution_id] = c
        withdrawals = {}
        for w_data in data.get("capital_withdrawals", []):
            w = CapitalWithdrawalEntity.from_dict(w_data)
            withdrawals[w.withdrawal_id] = w
        retained = RetainedEarningsEntity.from_dict(data["retained_earnings"])
        dividends = [
            DividendDeclarationEntity.from_dict(d) for d in data.get("dividend_declarations", [])
        ]
        return cls(
            equity_id=UUID(data["equity_id"]),
            legal_entity_id=UUID(data["legal_entity_id"]),
            legal_entity_name=data["legal_entity_name"],
            capital_contributions=contributions,
            capital_withdrawals=withdrawals,
            retained_earnings=retained,
            dividend_declarations=dividends,
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            created_by=data.get("created_by", "system"),
            version=data.get("version", 1),
        )

    def clone(self) -> EquityAggregate:
        new_id = uuid4()
        new_agg = EquityAggregate(
            equity_id=new_id,
            legal_entity_id=self.legal_entity_id,
            legal_entity_name=self.legal_entity_name,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            created_by=self.created_by,
            version=1,
        )
        # Clone contributions
        for c in self.capital_contributions.values():
            cloned_c = c.clone()
            new_agg = new_agg.add_capital_contribution(cloned_c, self.created_by)
        # Clone withdrawals
        for w in self.capital_withdrawals.values():
            cloned_w = w.clone()
            new_agg = new_agg.add_capital_withdrawal(cloned_w, self.created_by)
        # Clone retained earnings
        new_retained = self.retained_earnings.clone()
        object.__setattr__(new_agg, "retained_earnings", new_retained)
        # Clone dividends
        for d in self.dividend_declarations:
            cloned_d = d.clone()
            new_agg.dividend_declarations.append(cloned_d)
        new_agg._record_audit("CLONE", self.created_by, {"source": str(self.equity_id)})
        return new_agg

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "equity_id": str(self.equity_id),
            "legal_entity_name": self.legal_entity_name,
            "total_equity": str(self.total_equity),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def get_version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> EquityAggregate:
        new_agg = self._copy()
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        new_agg._record_audit("TOUCH", touched_by, {})
        return new_agg

    # ==================== AGGREGATE ROOT METHODS ====================

    def add_child(self, entity: Any, created_by: str) -> EquityAggregate:
        """Add child entity based on type."""
        if isinstance(entity, CapitalContributionEntity):
            return self.add_capital_contribution(entity, created_by)
        elif isinstance(entity, CapitalWithdrawalEntity):
            return self.add_capital_withdrawal(entity, created_by)
        elif isinstance(entity, DividendDeclarationEntity):
            return self.add_dividend_declaration(entity, created_by)
        else:
            raise EquityAggregateError(f"Unknown entity type: {type(entity)}")

    def remove_child(self, entity_id: UUID, entity_type: str, removed_by: str) -> EquityAggregate:
        """Remove child entity by type."""
        if entity_type == "contribution":
            return self.remove_capital_contribution(entity_id, removed_by)
        elif entity_type == "withdrawal":
            return self.remove_capital_withdrawal(entity_id, removed_by)
        elif entity_type == "dividend":
            return self.remove_dividend_declaration(entity_id, removed_by)
        else:
            raise EquityAggregateError(f"Unknown entity type: {entity_type}")

    def can_post(self, transaction_id: UUID, transaction_type: str) -> bool:
        if transaction_type == "contribution":
            contrib = self.capital_contributions.get(transaction_id)
            return contrib is not None and contrib.can_post
        elif transaction_type == "withdrawal":
            withdrawal = self.capital_withdrawals.get(transaction_id)
            return withdrawal is not None and withdrawal.can_post
        return False

    def post(self, transaction_id: UUID, transaction_type: str, posted_by: str) -> EquityAggregate:
        if transaction_type == "contribution":
            return self.post_capital_contribution(transaction_id, posted_by)
        elif transaction_type == "withdrawal":
            return self.post_capital_withdrawal(transaction_id, posted_by)
        else:
            raise EquityAggregateError(f"Cannot post transaction type: {transaction_type}")

    def can_approve(
        self, transaction_id: UUID, transaction_type: str, user_role: str = "user"
    ) -> bool:
        if transaction_type == "contribution":
            contrib = self.capital_contributions.get(transaction_id)
            return (
                contrib is not None
                and contrib.can_approve
                and user_role in ("finance_manager", "admin")
            )
        elif transaction_type == "withdrawal":
            withdrawal = self.capital_withdrawals.get(transaction_id)
            return (
                withdrawal is not None
                and withdrawal.can_approve
                and user_role in ("finance_manager", "admin")
            )
        elif transaction_type == "dividend":
            dividend = self.get_dividend_declaration(transaction_id)
            return dividend is not None and dividend.can_approve and user_role in ("board", "admin")
        return False

    def approve(
        self, transaction_id: UUID, transaction_type: str, approved_by: str
    ) -> EquityAggregate:
        if transaction_type == "contribution":
            return self.approve_capital_contribution(transaction_id, approved_by)
        elif transaction_type == "withdrawal":
            return self.approve_capital_withdrawal(transaction_id, approved_by)
        elif transaction_type == "dividend":
            return self.approve_dividend(transaction_id, approved_by)
        else:
            raise EquityAggregateError(f"Cannot approve transaction type: {transaction_type}")

    def can_reject(
        self, transaction_id: UUID, transaction_type: str, user_role: str = "user"
    ) -> bool:
        if transaction_type == "contribution":
            contrib = self.capital_contributions.get(transaction_id)
            return contrib is not None and contrib.status == ContributionStatus.DRAFT
        elif transaction_type == "withdrawal":
            withdrawal = self.capital_withdrawals.get(transaction_id)
            return withdrawal is not None and withdrawal.status == WithdrawalStatus.DRAFT
        return False

    def reject(
        self, transaction_id: UUID, transaction_type: str, rejected_by: str, reason: str
    ) -> EquityAggregate:
        if not self.can_reject(transaction_id, transaction_type):
            raise EquityAggregateError(f"Cannot reject {transaction_type} {transaction_id}")
        if transaction_type == "contribution":
            contrib = self.capital_contributions[transaction_id]
            cancelled = contrib.cancel(rejected_by, reason)
            new_contributions = dict(self.capital_contributions)
            new_contributions[transaction_id] = cancelled
            new_agg = self._copy()
            new_agg.capital_contributions = new_contributions
            new_agg.updated_at = datetime.now(UTC)
            new_agg.version = self.version + 1
            self._register_event(
                CapitalContributionCancelledEvent(
                    aggregate_id=self.equity_id,
                    aggregate_version=self.version + 1,
                    contribution=cancelled,
                    cancelled_by=rejected_by,
                    reason=reason,
                )
            )
            return new_agg
        else:
            raise EquityAggregateError(f"Reject not implemented for {transaction_type}")

    def can_cancel(self, transaction_id: UUID, transaction_type: str) -> bool:
        if transaction_type == "contribution":
            contrib = self.capital_contributions.get(transaction_id)
            return contrib is not None and contrib.can_cancel
        elif transaction_type == "withdrawal":
            withdrawal = self.capital_withdrawals.get(transaction_id)
            return withdrawal is not None and withdrawal.can_cancel
        elif transaction_type == "dividend":
            dividend = self.get_dividend_declaration(transaction_id)
            return dividend is not None and dividend.can_cancel
        return False

    def cancel(
        self, transaction_id: UUID, transaction_type: str, cancelled_by: str, reason: str
    ) -> EquityAggregate:
        if transaction_type == "contribution":
            return self.cancel_capital_contribution(transaction_id, cancelled_by, reason)
        elif transaction_type == "withdrawal":
            return self.cancel_capital_withdrawal(transaction_id, cancelled_by, reason)
        elif transaction_type == "dividend":
            return self.cancel_dividend(transaction_id, cancelled_by, reason)
        else:
            raise EquityAggregateError(f"Cannot cancel transaction type: {transaction_type}")

    def can_reverse(self, transaction_id: UUID, transaction_type: str) -> bool:
        return False  # Tidak ada reverse untuk equity

    def reverse(
        self, transaction_id: UUID, transaction_type: str, reversed_by: str, reason: str
    ) -> EquityAggregate:
        raise NotImplementedError("Reverse not applicable for equity transactions")

    def can_close(self) -> bool:
        return (
            self.total_equity == 0
            and len(self.capital_contributions) == 0
            and len(self.capital_withdrawals) == 0
        )

    def close(self, closed_by: str, reason: str) -> EquityAggregate:
        if not self.can_close():
            raise EquityAggregateError(
                "Cannot close equity aggregate with non-zero equity or active transactions"
            )
        new_agg = self._copy()
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        new_agg._record_audit("CLOSE", closed_by, {"reason": reason})
        return new_agg

    def can_reopen(self) -> bool:
        return True

    def reopen(self, reopened_by: str, reason: str) -> EquityAggregate:
        new_agg = self._copy()
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        new_agg._record_audit("REOPEN", reopened_by, {"reason": reason})
        return new_agg

    def can_archive(self) -> bool:
        return (
            len(self.capital_contributions) == 0
            and len(self.capital_withdrawals) == 0
            and len(self.dividend_declarations) == 0
        )

    def archive(self, archived_by: str, reason: str | None = None) -> EquityAggregate:
        if not self.can_archive():
            raise EquityAggregateError("Cannot archive aggregate with active transactions")
        new_agg = self._copy()
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        new_agg._record_audit("ARCHIVE", archived_by, {"reason": reason})
        return new_agg

    def can_unarchive(self) -> bool:
        return True

    def unarchive(self, unarchived_by: str) -> EquityAggregate:
        new_agg = self._copy()
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        new_agg._record_audit("UNARCHIVE", unarchived_by, {})
        return new_agg

    # ==================== EVENT METHODS ====================

    def register_event(self, event: DomainEvent) -> None:
        self._events.append(event)

    def get_events(self) -> list[DomainEvent]:
        return self._events.copy()

    def pull_events(self) -> list[DomainEvent]:
        events = self._events.copy()
        self._events.clear()
        return events

    def clear_events(self) -> None:
        self._events.clear()

    # ==================== PROPERTIES ====================

    @property
    def total_paid_in_capital(self) -> Decimal:
        total_contrib = sum(
            c.amount
            for c in self.capital_contributions.values()
            if c.status == ContributionStatus.POSTED
        )
        total_withdraw = sum(
            w.amount
            for w in self.capital_withdrawals.values()
            if w.status == WithdrawalStatus.POSTED
        )
        return total_contrib - total_withdraw

    @property
    def total_retained_earnings(self) -> Decimal:
        return self.retained_earnings.current_balance

    @property
    def total_equity(self) -> Decimal:
        return self.total_paid_in_capital + self.total_retained_earnings

    @property
    def total_posted_contributions(self) -> Decimal:
        return sum(
            c.amount
            for c in self.capital_contributions.values()
            if c.status == ContributionStatus.POSTED
        )

    @property
    def total_posted_withdrawals(self) -> Decimal:
        return sum(
            w.amount
            for w in self.capital_withdrawals.values()
            if w.status == WithdrawalStatus.POSTED
        )

    @property
    def total_dividends_declared(self) -> Decimal:
        return sum(d.total_amount for d in self.dividend_declarations)

    @property
    def total_dividends_paid(self) -> Decimal:
        return sum(d.total_paid for d in self.dividend_declarations)

    # ==================== QUERY METHODS ====================

    def get_capital_contribution(self, contribution_id: UUID) -> CapitalContributionEntity | None:
        return self.capital_contributions.get(contribution_id)

    def get_capital_withdrawal(self, withdrawal_id: UUID) -> CapitalWithdrawalEntity | None:
        return self.capital_withdrawals.get(withdrawal_id)

    def get_dividend_declaration(self, dividend_id: UUID) -> DividendDeclarationEntity | None:
        for d in self.dividend_declarations:
            if d.dividend_id == dividend_id:
                return d
        return None

    def get_contributions_by_shareholder(
        self, shareholder_id: UUID
    ) -> list[CapitalContributionEntity]:
        return [
            c for c in self.capital_contributions.values() if c.shareholder_id == shareholder_id
        ]

    def get_withdrawals_by_shareholder(self, shareholder_id: UUID) -> list[CapitalWithdrawalEntity]:
        return [w for w in self.capital_withdrawals.values() if w.shareholder_id == shareholder_id]

    def get_dividends_by_shareholder(self, shareholder_id: UUID) -> list[DividendDeclarationEntity]:
        return [
            d
            for d in self.dividend_declarations
            if any(a.shareholder_id == shareholder_id for a in d.allocations)
        ]

    def get_shareholder_net_capital(self, shareholder_id: UUID) -> Decimal:
        contributions = sum(
            c.amount
            for c in self.get_contributions_by_shareholder(shareholder_id)
            if c.status == ContributionStatus.POSTED
        )
        withdrawals = sum(
            w.amount
            for w in self.get_withdrawals_by_shareholder(shareholder_id)
            if w.status == WithdrawalStatus.POSTED
        )
        return contributions - withdrawals

    # ==================== COMMAND METHODS ====================

    def add_capital_contribution(
        self, contribution: CapitalContributionEntity, added_by: str
    ) -> EquityAggregate:
        if contribution.contribution_id in self.capital_contributions:
            raise DuplicateTransactionError(
                f"Contribution {contribution.contribution_id} already exists"
            )
        new_contributions = dict(self.capital_contributions)
        new_contributions[contribution.contribution_id] = contribution
        self._register_event(
            CapitalContributionRecordedEvent(
                aggregate_id=self.equity_id,
                aggregate_version=self.version + 1,
                contribution=contribution,
                recorded_by=added_by,
            )
        )
        return EquityAggregate(
            equity_id=self.equity_id,
            legal_entity_id=self.legal_entity_id,
            legal_entity_name=self.legal_entity_name,
            capital_contributions=new_contributions,
            capital_withdrawals=self.capital_withdrawals,
            retained_earnings=self.retained_earnings,
            dividend_declarations=self.dividend_declarations,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=added_by,
            version=self.version + 1,
        )

    def remove_capital_contribution(
        self, contribution_id: UUID, removed_by: str
    ) -> EquityAggregate:
        if contribution_id not in self.capital_contributions:
            raise TransactionNotFoundError(f"Contribution {contribution_id} not found")
        contrib = self.capital_contributions[contribution_id]
        if contrib.status != ContributionStatus.DRAFT:
            raise EquityAggregateError(
                f"Cannot remove non-draft contribution (status: {contrib.status.value})"
            )
        new_contributions = {
            k: v for k, v in self.capital_contributions.items() if k != contribution_id
        }
        new_agg = self._copy()
        new_agg.capital_contributions = new_contributions
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        new_agg._record_audit("REMOVE_CONTRIBUTION", removed_by, {"id": str(contribution_id)})
        return new_agg

    def add_capital_withdrawal(
        self, withdrawal: CapitalWithdrawalEntity, added_by: str
    ) -> EquityAggregate:
        if withdrawal.withdrawal_id in self.capital_withdrawals:
            raise DuplicateTransactionError(f"Withdrawal {withdrawal.withdrawal_id} already exists")
        # Validate sufficient paid-in capital
        new_total = self.total_paid_in_capital - withdrawal.amount
        if new_total < 0:
            raise InsufficientPaidInCapitalError(
                f"Withdrawal amount {withdrawal.amount} exceeds paid-in capital {self.total_paid_in_capital}"
            )
        new_withdrawals = dict(self.capital_withdrawals)
        new_withdrawals[withdrawal.withdrawal_id] = withdrawal
        self._register_event(
            CapitalWithdrawalRecordedEvent(
                aggregate_id=self.equity_id,
                aggregate_version=self.version + 1,
                withdrawal=withdrawal,
                recorded_by=added_by,
            )
        )
        return EquityAggregate(
            equity_id=self.equity_id,
            legal_entity_id=self.legal_entity_id,
            legal_entity_name=self.legal_entity_name,
            capital_contributions=self.capital_contributions,
            capital_withdrawals=new_withdrawals,
            retained_earnings=self.retained_earnings,
            dividend_declarations=self.dividend_declarations,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=added_by,
            version=self.version + 1,
        )

    def remove_capital_withdrawal(self, withdrawal_id: UUID, removed_by: str) -> EquityAggregate:
        if withdrawal_id not in self.capital_withdrawals:
            raise TransactionNotFoundError(f"Withdrawal {withdrawal_id} not found")
        withdrawal = self.capital_withdrawals[withdrawal_id]
        if withdrawal.status != WithdrawalStatus.DRAFT:
            raise EquityAggregateError(
                f"Cannot remove non-draft withdrawal (status: {withdrawal.status.value})"
            )
        new_withdrawals = {k: v for k, v in self.capital_withdrawals.items() if k != withdrawal_id}
        new_agg = self._copy()
        new_agg.capital_withdrawals = new_withdrawals
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        new_agg._record_audit("REMOVE_WITHDRAWAL", removed_by, {"id": str(withdrawal_id)})
        return new_agg

    def add_dividend_declaration(
        self, dividend: DividendDeclarationEntity, declared_by: str
    ) -> EquityAggregate:
        if dividend.total_amount > self.total_retained_earnings:
            raise InsufficientRetainedEarningsError(
                f"Dividend amount {dividend.total_amount} exceeds retained earnings {self.total_retained_earnings}"
            )
        new_dividends = self.dividend_declarations + [dividend]
        self._register_event(
            DividendDeclaredEvent(
                aggregate_id=self.equity_id,
                aggregate_version=self.version + 1,
                dividend=dividend,
                declared_by=declared_by,
            )
        )
        return EquityAggregate(
            equity_id=self.equity_id,
            legal_entity_id=self.legal_entity_id,
            legal_entity_name=self.legal_entity_name,
            capital_contributions=self.capital_contributions,
            capital_withdrawals=self.capital_withdrawals,
            retained_earnings=self.retained_earnings,
            dividend_declarations=new_dividends,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=declared_by,
            version=self.version + 1,
        )

    def remove_dividend_declaration(self, dividend_id: UUID, removed_by: str) -> EquityAggregate:
        idx = next(
            (i for i, d in enumerate(self.dividend_declarations) if d.dividend_id == dividend_id),
            None,
        )
        if idx is None:
            raise TransactionNotFoundError(f"Dividend {dividend_id} not found")
        dividend = self.dividend_declarations[idx]
        if dividend.status != DividendStatus.PROPOSED:
            raise EquityAggregateError(f"Cannot remove dividend in status {dividend.status.value}")
        new_dividends = self.dividend_declarations[:idx] + self.dividend_declarations[idx + 1 :]
        new_agg = self._copy()
        new_agg.dividend_declarations = new_dividends
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        new_agg._record_audit("REMOVE_DIVIDEND", removed_by, {"id": str(dividend_id)})
        return new_agg

    def approve_capital_contribution(
        self, contribution_id: UUID, approved_by: str
    ) -> EquityAggregate:
        contrib = self.get_capital_contribution(contribution_id)
        if contrib is None:
            raise TransactionNotFoundError(f"Contribution {contribution_id} not found")
        if not contrib.can_approve:
            raise EquityAggregateError(
                f"Cannot approve contribution in status {contrib.status.value}"
            )
        new_contrib = contrib.approve(approved_by)
        new_contributions = dict(self.capital_contributions)
        new_contributions[contribution_id] = new_contrib
        self._register_event(
            CapitalContributionApprovedEvent(
                aggregate_id=self.equity_id,
                aggregate_version=self.version + 1,
                contribution=new_contrib,
                approved_by=approved_by,
            )
        )
        new_agg = self._copy()
        new_agg.capital_contributions = new_contributions
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        return new_agg

    def approve_capital_withdrawal(self, withdrawal_id: UUID, approved_by: str) -> EquityAggregate:
        withdrawal = self.get_capital_withdrawal(withdrawal_id)
        if withdrawal is None:
            raise TransactionNotFoundError(f"Withdrawal {withdrawal_id} not found")
        if not withdrawal.can_approve:
            raise EquityAggregateError(
                f"Cannot approve withdrawal in status {withdrawal.status.value}"
            )
        new_withdrawal = withdrawal.approve(approved_by)
        new_withdrawals = dict(self.capital_withdrawals)
        new_withdrawals[withdrawal_id] = new_withdrawal
        self._register_event(
            CapitalWithdrawalApprovedEvent(
                aggregate_id=self.equity_id,
                aggregate_version=self.version + 1,
                withdrawal=new_withdrawal,
                approved_by=approved_by,
            )
        )
        new_agg = self._copy()
        new_agg.capital_withdrawals = new_withdrawals
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        return new_agg

    def approve_dividend(self, dividend_id: UUID, approved_by: str) -> EquityAggregate:
        dividend = self.get_dividend_declaration(dividend_id)
        if dividend is None:
            raise TransactionNotFoundError(f"Dividend {dividend_id} not found")
        if not dividend.can_approve:
            raise EquityAggregateError(f"Cannot approve dividend in status {dividend.status.value}")
        new_dividend = dividend.approve(approved_by)
        new_dividends = [
            new_dividend if d.dividend_id == dividend_id else d for d in self.dividend_declarations
        ]
        self._register_event(
            DividendApprovedEvent(
                aggregate_id=self.equity_id,
                aggregate_version=self.version + 1,
                dividend=new_dividend,
                approved_by=approved_by,
            )
        )
        new_agg = self._copy()
        new_agg.dividend_declarations = new_dividends
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        return new_agg

    def post_capital_contribution(self, contribution_id: UUID, posted_by: str) -> EquityAggregate:
        contrib = self.get_capital_contribution(contribution_id)
        if contrib is None:
            raise TransactionNotFoundError(f"Contribution {contribution_id} not found")
        if not contrib.can_post:
            raise EquityAggregateError(f"Cannot post contribution in status {contrib.status.value}")
        new_contrib = contrib.post(posted_by)
        new_contributions = dict(self.capital_contributions)
        new_contributions[contribution_id] = new_contrib
        self._register_event(
            CapitalContributionPostedEvent(
                aggregate_id=self.equity_id,
                aggregate_version=self.version + 1,
                contribution=new_contrib,
                posted_by=posted_by,
            )
        )
        new_agg = self._copy()
        new_agg.capital_contributions = new_contributions
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        return new_agg

    def post_capital_withdrawal(self, withdrawal_id: UUID, posted_by: str) -> EquityAggregate:
        withdrawal = self.get_capital_withdrawal(withdrawal_id)
        if withdrawal is None:
            raise TransactionNotFoundError(f"Withdrawal {withdrawal_id} not found")
        if not withdrawal.can_post:
            raise EquityAggregateError(
                f"Cannot post withdrawal in status {withdrawal.status.value}"
            )
        new_withdrawal = withdrawal.post(posted_by)
        new_withdrawals = dict(self.capital_withdrawals)
        new_withdrawals[withdrawal_id] = new_withdrawal
        self._register_event(
            CapitalWithdrawalPostedEvent(
                aggregate_id=self.equity_id,
                aggregate_version=self.version + 1,
                withdrawal=new_withdrawal,
                posted_by=posted_by,
            )
        )
        new_agg = self._copy()
        new_agg.capital_withdrawals = new_withdrawals
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        return new_agg

    def cancel_capital_contribution(
        self, contribution_id: UUID, cancelled_by: str, reason: str
    ) -> EquityAggregate:
        contrib = self.get_capital_contribution(contribution_id)
        if contrib is None:
            raise TransactionNotFoundError(f"Contribution {contribution_id} not found")
        if not contrib.can_cancel:
            raise EquityAggregateError(
                f"Cannot cancel contribution in status {contrib.status.value}"
            )
        new_contrib = contrib.cancel(cancelled_by, reason)
        new_contributions = dict(self.capital_contributions)
        new_contributions[contribution_id] = new_contrib
        self._register_event(
            CapitalContributionCancelledEvent(
                aggregate_id=self.equity_id,
                aggregate_version=self.version + 1,
                contribution=new_contrib,
                cancelled_by=cancelled_by,
                reason=reason,
            )
        )
        new_agg = self._copy()
        new_agg.capital_contributions = new_contributions
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        return new_agg

    def cancel_capital_withdrawal(
        self, withdrawal_id: UUID, cancelled_by: str, reason: str
    ) -> EquityAggregate:
        withdrawal = self.get_capital_withdrawal(withdrawal_id)
        if withdrawal is None:
            raise TransactionNotFoundError(f"Withdrawal {withdrawal_id} not found")
        if not withdrawal.can_cancel:
            raise EquityAggregateError(
                f"Cannot cancel withdrawal in status {withdrawal.status.value}"
            )
        new_withdrawal = withdrawal.cancel(cancelled_by, reason)
        new_withdrawals = dict(self.capital_withdrawals)
        new_withdrawals[withdrawal_id] = new_withdrawal
        self._register_event(
            CapitalWithdrawalCancelledEvent(
                aggregate_id=self.equity_id,
                aggregate_version=self.version + 1,
                withdrawal=new_withdrawal,
                cancelled_by=cancelled_by,
                reason=reason,
            )
        )
        new_agg = self._copy()
        new_agg.capital_withdrawals = new_withdrawals
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        return new_agg

    def cancel_dividend(self, dividend_id: UUID, cancelled_by: str, reason: str) -> EquityAggregate:
        dividend = self.get_dividend_declaration(dividend_id)
        if dividend is None:
            raise TransactionNotFoundError(f"Dividend {dividend_id} not found")
        if not dividend.can_cancel:
            raise EquityAggregateError(f"Cannot cancel dividend in status {dividend.status.value}")
        new_dividend = dividend.cancel(cancelled_by, reason)
        new_dividends = [
            new_dividend if d.dividend_id == dividend_id else d for d in self.dividend_declarations
        ]
        self._register_event(
            DividendCancelledEvent(
                aggregate_id=self.equity_id,
                aggregate_version=self.version + 1,
                dividend=new_dividend,
                cancelled_by=cancelled_by,
                reason=reason,
            )
        )
        new_agg = self._copy()
        new_agg.dividend_declarations = new_dividends
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        return new_agg

    def pay_dividend(
        self,
        dividend_id: UUID,
        amount: Decimal,
        paid_by: str,
        payment_date: datetime | None = None,
        allocation_filter: UUID | None = None,
    ) -> EquityAggregate:
        dividend = self.get_dividend_declaration(dividend_id)
        if dividend is None:
            raise TransactionNotFoundError(f"Dividend {dividend_id} not found")
        if not dividend.can_pay:
            raise EquityAggregateError(f"Cannot pay dividend in status {dividend.status.value}")
        if amount <= 0:
            raise EquityAggregateError("Payment amount must be positive")
        if amount > dividend.unpaid_amount:
            raise EquityAggregateError(
                f"Payment amount {amount} exceeds unpaid amount {dividend.unpaid_amount}"
            )

        if payment_date is None:
            payment_date = datetime.now(UTC)
        new_dividend = dividend.record_payment(amount, paid_by, payment_date, allocation_filter)
        # Update retained earnings
        new_retained = self.retained_earnings.record_dividend(
            amount,
            dividend.dividend_number,
            paid_by,
            f"Dividend payment for {dividend.dividend_number}",
            dividend.dividend_id.hex,
        )
        new_dividends = [
            new_dividend if d.dividend_id == dividend_id else d for d in self.dividend_declarations
        ]

        event_cls = (
            DividendPartiallyPaidEvent
            if new_dividend.status == DividendStatus.PARTIALLY_PAID
            else DividendPaidEvent
        )
        self._register_event(
            event_cls(
                aggregate_id=self.equity_id,
                aggregate_version=self.version + 1,
                dividend=new_dividend,
                paid_amount=amount,
                paid_by=paid_by,
                total_paid=new_dividend.total_paid
                if event_cls == DividendPaidEvent
                else new_dividend.total_paid,
                unpaid_amount=new_dividend.unpaid_amount
                if event_cls == DividendPartiallyPaidEvent
                else None,
            )
        )

        new_agg = self._copy()
        new_agg.retained_earnings = new_retained
        new_agg.dividend_declarations = new_dividends
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        return new_agg

    def add_net_income(
        self, net_income: Decimal, period: str, updated_by: str, description: str = ""
    ) -> EquityAggregate:
        new_retained = self.retained_earnings.add_net_income(
            net_income, period, updated_by, description
        )
        self._register_event(
            RetainedEarningsUpdatedEvent(
                aggregate_id=self.equity_id,
                aggregate_version=self.version + 1,
                legal_entity_id=self.legal_entity_id,
                period=period,
                net_income=net_income,
                new_balance=new_retained.current_balance,
                updated_by=updated_by,
            )
        )
        new_agg = self._copy()
        new_agg.retained_earnings = new_retained
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        return new_agg

    def add_prior_period_adjustment(
        self, adjustment: Decimal, period: str, updated_by: str, description: str = ""
    ) -> EquityAggregate:
        new_retained = self.retained_earnings.add_prior_period_adjustment(
            adjustment, period, updated_by, description
        )
        self._register_event(
            RetainedEarningsAdjustedEvent(
                aggregate_id=self.equity_id,
                aggregate_version=self.version + 1,
                legal_entity_id=self.legal_entity_id,
                period=period,
                adjustment=adjustment,
                description=description,
                new_balance=new_retained.current_balance,
                updated_by=updated_by,
            )
        )
        new_agg = self._copy()
        new_agg.retained_earnings = new_retained
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        return new_agg

    # ==================== STATISTICS ====================

    def get_equity_summary(self) -> dict[str, Any]:
        return {
            "legal_entity_id": str(self.legal_entity_id),
            "legal_entity_name": self.legal_entity_name,
            "paid_in_capital": str(self.total_paid_in_capital),
            "retained_earnings": str(self.total_retained_earnings),
            "total_equity": str(self.total_equity),
            "total_posted_contributions": str(self.total_posted_contributions),
            "total_posted_withdrawals": str(self.total_posted_withdrawals),
            "total_dividends_declared": str(self.total_dividends_declared),
            "total_dividends_paid": str(self.total_dividends_paid),
            "contributions_count": len(self.capital_contributions),
            "withdrawals_count": len(self.capital_withdrawals),
            "dividends_count": len(self.dividend_declarations),
            "retained_earnings_entries_count": len(self.retained_earnings.entries),
        }

    # ==================== PRIVATE HELPERS ====================

    def _copy(self) -> EquityAggregate:
        return EquityAggregate(
            equity_id=self.equity_id,
            legal_entity_id=self.legal_entity_id,
            legal_entity_name=self.legal_entity_name,
            capital_contributions=self.capital_contributions.copy(),
            capital_withdrawals=self.capital_withdrawals.copy(),
            retained_earnings=self.retained_earnings,
            dividend_declarations=self.dividend_declarations.copy(),
            created_at=self.created_at,
            updated_at=self.updated_at,
            created_by=self.created_by,
            version=self.version,
        )


# ============================================================================
# Repository Implementation (Real)
# ============================================================================


class EquityRepository:
    _storage: ClassVar[dict[UUID, EquityAggregate]] = {}

    @classmethod
    async def get_by_legal_entity(cls, legal_entity_id: UUID) -> EquityAggregate | None:
        for agg in cls._storage.values():
            if agg.legal_entity_id == legal_entity_id:
                return agg
        return None

    @classmethod
    async def get_by_id(cls, equity_id: UUID) -> EquityAggregate | None:
        return cls._storage.get(equity_id)

    @classmethod
    async def get_all(cls) -> list[EquityAggregate]:
        return list(cls._storage.values())

    @classmethod
    async def save(cls, equity: EquityAggregate) -> None:
        cls._storage[equity.equity_id] = equity

    @classmethod
    async def update(cls, equity: EquityAggregate) -> None:
        cls._storage[equity.equity_id] = equity

    @classmethod
    async def delete(cls, equity_id: UUID) -> None:
        if equity_id in cls._storage:
            del cls._storage[equity_id]

    @classmethod
    async def exists(cls, equity_id: UUID) -> bool:
        return equity_id in cls._storage

    @classmethod
    async def count(cls) -> int:
        return len(cls._storage)

    @classmethod
    async def list(cls, limit: int = 100, offset: int = 0) -> list[EquityAggregate]:
        aggregates = list(cls._storage.values())
        return aggregates[offset : offset + limit]

    @classmethod
    async def paginate(cls, page: int = 1, per_page: int = 20) -> tuple[list[EquityAggregate], int]:
        aggregates = list(cls._storage.values())
        total = len(aggregates)
        start = (page - 1) * per_page
        end = start + per_page
        return aggregates[start:end], total

    @classmethod
    async def search(cls, query: str, fields: list[str] | None = None) -> list[EquityAggregate]:
        if fields is None:
            fields = ["equity_id", "legal_entity_name"]
        query_lower = query.lower()
        results = []
        for agg in cls._storage.values():
            for field in fields:
                value = getattr(agg, field, "")
                if value and query_lower in str(value).lower():
                    results.append(agg)
                    break
        return results

    @classmethod
    async def lock(cls, equity_id: UUID, locked_by: str, reason: str) -> EquityAggregate:
        agg = await cls.get_by_id(equity_id)
        if not agg:
            raise ValueError(f"Aggregate {equity_id} not found")
        locked = agg.lock(locked_by, reason)
        await cls.save(locked)
        return locked

    @classmethod
    async def unlock(cls, equity_id: UUID, unlocked_by: str) -> EquityAggregate:
        agg = await cls.get_by_id(equity_id)
        if not agg:
            raise ValueError(f"Aggregate {equity_id} not found")
        unlocked = agg.unlock(unlocked_by)
        await cls.save(unlocked)
        return unlocked

    @classmethod
    async def clear(cls) -> None:
        cls._storage.clear()


__all__ = [
    "DuplicateTransactionError",
    "EquityAggregate",
    "EquityAggregateError",
    "EquityRepository",
    "InsufficientPaidInCapitalError",
    "InsufficientRetainedEarningsError",
    "TransactionNotFoundError",
]
