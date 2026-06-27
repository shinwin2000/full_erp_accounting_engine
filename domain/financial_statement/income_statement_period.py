#!/usr/bin/env python3
"""
Module: income_statement_period.py
Layer: Domain / Financial Statement
Responsibility: Represent income statement (laba rugi) for a period.
               Immutable object with all entity dasar methods, profitability ratios,
               common size analysis, serialization, cloning, snapshot, audit trail.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any, ClassVar
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


# ============================================================================
# Custom Exceptions
# ============================================================================


class IncomeStatementError(ValueError):
    pass


# ============================================================================
# Income Statement Period Entity
# ============================================================================


@dataclass(frozen=True)
class IncomeStatementPeriod:
    statement_id: UUID
    legal_entity_id: UUID
    period_start: date
    period_end: date
    revenue: Decimal
    cogs: Decimal
    gross_profit: Decimal
    operating_expenses: Decimal
    operating_income: Decimal
    other_income: Decimal
    other_expenses: Decimal
    income_before_tax: Decimal
    tax_expense: Decimal
    net_income: Decimal
    currency: str = "IDR"
    description: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str = "system"
    version: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)

    _audit_trail: ClassVar[list[dict[str, Any]]] = []
    _snapshots: ClassVar[list[dict[str, Any]]] = []

    def __post_init__(self) -> None:
        self._validate()
        self._take_snapshot()

    def _validate(self) -> None:
        # Validate currency
        if not self.currency or len(self.currency) != 3:
            raise IncomeStatementError(f"Invalid currency: {self.currency}")

        # Validate dates
        if self.period_end <= self.period_start:
            raise IncomeStatementError(
                f"Period end {self.period_end} must be after period start {self.period_start}"
            )

        # Validate amounts are Decimal
        for field_name in [
            "revenue",
            "cogs",
            "gross_profit",
            "operating_expenses",
            "operating_income",
            "other_income",
            "other_expenses",
            "income_before_tax",
            "tax_expense",
            "net_income",
        ]:
            val = getattr(self, field_name)
            if not isinstance(val, Decimal):
                object.__setattr__(self, field_name, Decimal(str(val)))
            object.__setattr__(
                self, field_name, val.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
            )

        # Validate gross profit
        computed_gross = self.revenue - self.cogs
        if computed_gross != self.gross_profit:
            raise IncomeStatementError(
                f"Gross profit mismatch: computed {computed_gross} != {self.gross_profit}"
            )

        # Validate operating income
        computed_op = self.gross_profit - self.operating_expenses
        if computed_op != self.operating_income:
            raise IncomeStatementError(
                f"Operating income mismatch: computed {computed_op} != {self.operating_income}"
            )

        # Validate income before tax
        computed_ibt = self.operating_income + self.other_income - self.other_expenses
        if computed_ibt != self.income_before_tax:
            raise IncomeStatementError(
                f"Income before tax mismatch: computed {computed_ibt} != {self.income_before_tax}"
            )

        # Validate net income
        computed_net = self.income_before_tax - self.tax_expense
        if computed_net != self.net_income:
            raise IncomeStatementError(
                f"Net income mismatch: computed {computed_net} != {self.net_income}"
            )

        # Validate timestamps
        if self.created_at.tzinfo is None:
            object.__setattr__(self, "created_at", self.created_at.replace(tzinfo=UTC))

        if self.version < 1:
            raise IncomeStatementError("Version must be >= 1")

    def _take_snapshot(self) -> None:
        snapshot = {
            "version": self.version,
            "statement_id": str(self.statement_id),
            "period": f"{self.period_start.isoformat()} to {self.period_end.isoformat()}",
            "revenue": str(self.revenue),
            "net_income": str(self.net_income),
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
            "statement_id": str(self.statement_id),
            "details": details,
        }
        self._audit_trail.append(entry)

    # ==================== ENTITY DASAR METHODS ====================

    def create(self, created_by: str) -> IncomeStatementPeriod:
        self._record_audit(
            "CREATE", created_by, {"period": f"{self.period_start} to {self.period_end}"}
        )
        return self

    def update(self, updated_by: str, **kwargs) -> IncomeStatementPeriod:
        data = self.to_dict()
        for key, value in kwargs.items():
            if key not in ("statement_id", "created_at", "created_by", "version"):
                data[key] = value
        new_statement = self.from_dict(data)
        new_statement._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new_statement

    def delete(self, deleted_by: str, reason: str | None = None) -> IncomeStatementPeriod:
        new_statement = self._copy()
        new_statement._record_audit("DELETE", deleted_by, {"reason": reason})
        return new_statement

    def restore(self, restored_by: str) -> IncomeStatementPeriod:
        new_statement = self._copy()
        new_statement._record_audit("RESTORE", restored_by, {})
        return new_statement

    def activate(self, activated_by: str) -> IncomeStatementPeriod:
        new_statement = self._copy()
        new_statement._record_audit("ACTIVATE", activated_by, {})
        return new_statement

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> IncomeStatementPeriod:
        new_statement = self._copy()
        new_statement._record_audit("DEACTIVATE", deactivated_by, {"reason": reason})
        return new_statement

    def lock(self, locked_by: str, reason: str) -> IncomeStatementPeriod:
        new_statement = self._copy()
        new_statement.metadata["locked_by"] = locked_by
        new_statement.metadata["locked_at"] = datetime.now(UTC).isoformat()
        new_statement.metadata["lock_reason"] = reason
        new_statement._record_audit("LOCK", locked_by, {"reason": reason})
        return new_statement

    def unlock(self, unlocked_by: str) -> IncomeStatementPeriod:
        new_statement = self._copy()
        new_statement.metadata.pop("locked_by", None)
        new_statement.metadata.pop("locked_at", None)
        new_statement.metadata.pop("lock_reason", None)
        new_statement._record_audit("UNLOCK", unlocked_by, {})
        return new_statement

    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
        except IncomeStatementError as e:
            errors.append(str(e))
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "statement_id": str(self.statement_id),
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "statement_id": str(self.statement_id),
            "legal_entity_id": str(self.legal_entity_id),
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "revenue": str(self.revenue),
            "cogs": str(self.cogs),
            "gross_profit": str(self.gross_profit),
            "operating_expenses": str(self.operating_expenses),
            "operating_income": str(self.operating_income),
            "other_income": str(self.other_income),
            "other_expenses": str(self.other_expenses),
            "income_before_tax": str(self.income_before_tax),
            "tax_expense": str(self.tax_expense),
            "net_income": str(self.net_income),
            "currency": self.currency,
            "description": self.description,
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
            "version": self.version,
            "metadata": self.metadata,
            "gross_margin": str(self.gross_margin),
            "operating_margin": str(self.operating_margin),
            "net_margin": str(self.net_margin),
            "effective_tax_rate": str(self.effective_tax_rate),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IncomeStatementPeriod:
        return cls(
            statement_id=UUID(data["statement_id"]),
            legal_entity_id=UUID(data["legal_entity_id"]),
            period_start=date.fromisoformat(data["period_start"]),
            period_end=date.fromisoformat(data["period_end"]),
            revenue=Decimal(data["revenue"]),
            cogs=Decimal(data["cogs"]),
            gross_profit=Decimal(data["gross_profit"]),
            operating_expenses=Decimal(data["operating_expenses"]),
            operating_income=Decimal(data["operating_income"]),
            other_income=Decimal(data["other_income"]),
            other_expenses=Decimal(data["other_expenses"]),
            income_before_tax=Decimal(data["income_before_tax"]),
            tax_expense=Decimal(data["tax_expense"]),
            net_income=Decimal(data["net_income"]),
            currency=data.get("currency", "IDR"),
            description=data.get("description", ""),
            created_at=datetime.fromisoformat(data["created_at"]),
            created_by=data.get("created_by", "system"),
            version=data.get("version", 1),
            metadata=data.get("metadata", {}),
        )

    def clone(self) -> IncomeStatementPeriod:
        new_id = uuid4()
        now = datetime.now(UTC)
        cloned = IncomeStatementPeriod(
            statement_id=new_id,
            legal_entity_id=self.legal_entity_id,
            period_start=self.period_start,
            period_end=self.period_end,
            revenue=self.revenue,
            cogs=self.cogs,
            gross_profit=self.gross_profit,
            operating_expenses=self.operating_expenses,
            operating_income=self.operating_income,
            other_income=self.other_income,
            other_expenses=self.other_expenses,
            income_before_tax=self.income_before_tax,
            tax_expense=self.tax_expense,
            net_income=self.net_income,
            currency=self.currency,
            description=f"Cloned from {self.statement_id}",
            created_at=now,
            created_by=self.created_by,
            version=1,
        )
        cloned._record_audit("CLONE", self.created_by, {"source": str(self.statement_id)})
        return cloned

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "statement_id": str(self.statement_id),
            "period": f"{self.period_start.isoformat()} to {self.period_end.isoformat()}",
            "revenue": str(self.revenue),
            "net_income": str(self.net_income),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def get_version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> IncomeStatementPeriod:
        new_statement = self._copy()
        new_statement._record_audit("TOUCH", touched_by, {})
        return new_statement

    # ==================== PROPERTIES & RATIOS ====================

    @property
    def gross_margin(self) -> Decimal:
        if self.revenue == 0:
            return Decimal("0")
        return (self.gross_profit / self.revenue * 100).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_EVEN
        )

    @property
    def operating_margin(self) -> Decimal:
        if self.revenue == 0:
            return Decimal("0")
        return (self.operating_income / self.revenue * 100).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_EVEN
        )

    @property
    def net_margin(self) -> Decimal:
        if self.revenue == 0:
            return Decimal("0")
        return (self.net_income / self.revenue * 100).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_EVEN
        )

    @property
    def effective_tax_rate(self) -> Decimal:
        if self.income_before_tax == 0:
            return Decimal("0")
        return (self.tax_expense / self.income_before_tax * 100).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_EVEN
        )

    @property
    def revenue_growth(self, previous_revenue: Decimal | None = None) -> Decimal | None:
        if previous_revenue is None:
            return None
        if previous_revenue == 0:
            return Decimal("0") if self.revenue == 0 else Decimal("inf")
        return ((self.revenue - previous_revenue) / previous_revenue * 100).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_EVEN
        )

    @property
    def expense_ratio(self) -> Decimal:
        if self.revenue == 0:
            return Decimal("0")
        return (self.operating_expenses / self.revenue * 100).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_EVEN
        )

    # ==================== PRIVATE HELPERS ====================

    def _copy(self) -> IncomeStatementPeriod:
        return IncomeStatementPeriod(
            statement_id=self.statement_id,
            legal_entity_id=self.legal_entity_id,
            period_start=self.period_start,
            period_end=self.period_end,
            revenue=self.revenue,
            cogs=self.cogs,
            gross_profit=self.gross_profit,
            operating_expenses=self.operating_expenses,
            operating_income=self.operating_income,
            other_income=self.other_income,
            other_expenses=self.other_expenses,
            income_before_tax=self.income_before_tax,
            tax_expense=self.tax_expense,
            net_income=self.net_income,
            currency=self.currency,
            description=self.description,
            created_at=self.created_at,
            created_by=self.created_by,
            version=self.version,
            metadata=self.metadata.copy(),
        )


__all__ = ["IncomeStatementError", "IncomeStatementPeriod"]
