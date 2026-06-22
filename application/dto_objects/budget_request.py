#!/usr/bin/env python3
"""
Module: budget_request.py
Layer: Application / DTO Objects
Responsibility: Data Transfer Objects untuk modul Budget.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID


# ============================================================================
# REQUEST DTOs
# ============================================================================


@dataclass(kw_only=True)
class BudgetLineCreateRequest:
    """DTO untuk membuat budget line."""
    account_id: UUID
    amount: Decimal
    note: str | None = None


@dataclass(kw_only=True)
class BudgetCreateRequest:
    """DTO untuk membuat budget baru."""
    budget_code: str
    budget_name: str
    budget_type: str  # operational, capital, cash, project, department, fixed_asset, sales, production, labor
    fiscal_year: int
    period: str  # monthly, quarterly, yearly
    version: str = "1.0"
    effective_date: date
    expiry_date: date | None = None
    currency: str = "IDR"
    lines: list[dict[str, Any]]  # list of {account_id, amount, note}
    notes: str | None = None
    tags: list[str] | None = None
    created_by: UUID
    legal_entity_id: UUID


@dataclass(kw_only=True)
class BudgetUpdateRequest:
    """DTO untuk update budget."""
    id: UUID
    budget_name: str | None = None
    effective_date: date | None = None
    expiry_date: date | None = None
    notes: str | None = None
    tags: list[str] | None = None
    status: str | None = None
    updated_by: UUID
    legal_entity_id: UUID


@dataclass(kw_only=True)
class BudgetLineUpdateRequest:
    """DTO untuk update budget line."""
    line_id: UUID
    amount: Decimal
    note: str | None = None


@dataclass(kw_only=True)
class BudgetQueryRequest:
    """DTO untuk query budget."""
    legal_entity_id: UUID | None = None
    fiscal_year: int | None = None
    budget_type: str | None = None
    status: str | None = None
    is_active: bool | None = None
    search: str | None = None
    page: int = 1
    page_size: int = 20


@dataclass(kw_only=True)
class BudgetAdjustRequest:
    """DTO untuk adjustment budget."""
    budget_id: UUID
    adjustment_amount: Decimal
    adjustment_reason: str
    user_id: UUID
    legal_entity_id: UUID


@dataclass(kw_only=True)
class BudgetTransferRequest:
    """DTO untuk transfer budget antar akun."""
    budget_id: UUID | None = None
    from_account_id: UUID
    to_account_id: UUID
    amount: Decimal
    reason: str
    effective_date: date
    transferred_by: UUID
    legal_entity_id: UUID


# ============================================================================
# RESPONSE DTOs
# ============================================================================


@dataclass(kw_only=True)
class BudgetResponse:
    """Response untuk budget."""
    id: UUID
    budget_code: str
    budget_name: str
    budget_type: str
    fiscal_year: int
    period: str
    version: str
    status: str
    effective_date: date
    expiry_date: date | None
    currency: str
    total_amount: Decimal
    actual_amount_ytd: Decimal
    variance_amount: Decimal
    variance_percent: float
    consumption_percent: float
    notes: str | None
    tags: list[str] | None
    is_locked: bool
    created_at: datetime
    updated_at: datetime
    created_by: UUID
    created_by_name: str | None
    approved_at: datetime | None
    approved_by: UUID | None
    approved_by_name: str | None
    lines: list[dict[str, Any]]


@dataclass(kw_only=True)
class BudgetVersionResponse:
    """Response untuk versi budget."""
    id: UUID
    budget_code: str
    version: str
    status: str
    total_amount: Decimal
    effective_date: date
    created_at: datetime
    created_by: UUID
    created_by_name: str | None


@dataclass(kw_only=True)
class BudgetTransferResponse:
    """Response untuk transfer budget."""
    transfer_id: UUID
    budget_id: UUID
    from_account_id: UUID
    from_account_code: str
    from_account_name: str
    to_account_id: UUID
    to_account_code: str
    to_account_name: str
    amount: Decimal
    reason: str
    effective_date: date
    created_at: datetime
    created_by: UUID
    created_by_name: str | None
    approved_at: datetime | None
    approved_by: UUID | None


@dataclass(kw_only=True)
class BudgetVsActualLineResponse:
    """Line dalam response budget vs actual."""
    account_id: UUID
    account_code: str
    account_name: str
    budget_amount: Decimal
    actual_amount: Decimal
    variance_amount: Decimal
    variance_percent: float
    variance_type: str
    consumption_percent: float
    remaining_budget: Decimal


@dataclass(kw_only=True)
class BudgetVsActualResponse:
    """Response budget vs actual."""
    budget_id: UUID
    budget_name: str
    fiscal_year: int
    period: int
    period_name: str
    total_budget: Decimal
    total_actual: Decimal
    total_variance: Decimal
    variance_percent: float
    variance_type: str
    consumption_rate: float
    remaining_budget: Decimal
    lines: list[BudgetVsActualLineResponse]
    generated_at: datetime


@dataclass(kw_only=True)
class BudgetDashboardResponse:
    """Response dashboard budget."""
    as_of_date: date
    total_budgets: int
    active_budgets: int
    total_budget_amount: Decimal
    total_actual_ytd: Decimal
    total_variance: Decimal
    overall_consumption_rate: float
    by_type: dict[str, dict[str, Any]]
    by_status: dict[str, int]
    top_variance_items: list[dict[str, Any]]
    alerts: list[dict[str, Any]]
    generated_at: datetime


@dataclass(kw_only=True)
class BudgetAlertResponse:
    """Response alert budget."""
    budget_id: UUID
    budget_name: str
    account_id: UUID
    account_code: str
    account_name: str
    budget_amount: Decimal
    actual_amount: Decimal
    consumption_percent: float
    threshold_percent: float
    message: str
    severity: str
    created_at: datetime


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "BudgetAlertResponse",
    "BudgetCreateRequest",
    "BudgetDashboardResponse",
    "BudgetLineCreateRequest",
    "BudgetLineUpdateRequest",
    "BudgetQueryRequest",
    "BudgetResponse",
    "BudgetTransferRequest",
    "BudgetTransferResponse",
    "BudgetUpdateRequest",
    "BudgetVersionResponse",
    "BudgetVsActualLineResponse",
    "BudgetVsActualResponse",
]