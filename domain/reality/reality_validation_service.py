#!/usr/bin/env python3
"""
Module: reality_validation_service.py
Layer: 5 - Reality, Intent, Causality / Reality
Responsibility: Validasi apakah event ekonomi sah untuk direkam.
               Memeriksa kelengkapan, konsistensi, dan kepatuhan event ekonomi
               sebelum dipetakan ke jurnal akuntansi. Termasuk validasi
               data wajib, batasan bisnis, dan aturan spesifik per jenis event.

Dependencies:
- standard library (hashlib, json, logging, dataclass, datetime, decimal, enum, typing, uuid, threading)
- reality.economic_event_immutable (EconomicEvent, EconomicEventType, get_economic_event_service)
- reality.financial_obligation (get_financial_obligation_service)
- reality.financial_entitlement (get_financial_entitlement_service)
- kernel.context_holder (get_current_user) -> lazy import to avoid AST drift

Audit: Setiap event yang gagal validasi dictat.
"""

from __future__ import annotations

import hashlib
import importlib
import logging
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from domain.reality.economic_event_immutable import (
    EconomicEvent,
    EconomicEventStatus,
    EconomicEventType,
    get_economic_event_service,
)
from domain.reality.financial_entitlement import get_financial_entitlement_service
from domain.reality.financial_obligation import get_financial_obligation_service

logger = logging.getLogger(__name__)


# ============================================================================
# Lazy helper untuk menghindari AST drift (domain -> kernel)
# ============================================================================

def _get_current_user() -> str | None:
    """Lazy import kernel.context_holder.get_current_user."""
    try:
        mod = importlib.import_module("kernel.context_holder")
        get_current_user = mod.get_current_user
        return get_current_user()
    except Exception:
        return None


# === 1. CONSTANTS & ENUMS ===


class ValidationSeverity(Enum):
    """Severity kegagalan validasi."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class ValidationIssue:
    """Isu yang ditemukan saat validasi."""

    field: str
    message: str
    severity: ValidationSeverity
    code: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "message": self.message,
            "severity": self.severity.value,
            "code": self.code,
        }


@dataclass
class ValidationResult:
    """Hasil validasi event ekonomi."""

    is_valid: bool
    issues: list[ValidationIssue]
    warnings: list[ValidationIssue]
    requires_approval: bool = False
    requires_dual_control: bool = False
    validation_id: UUID = field(default_factory=uuid4)
    validated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    validated_by: str = ""
    cryptographic_hash: str = ""

    def compute_hash(self) -> str:
        content = (
            f"{self.validation_id}|{self.is_valid}|{len(self.issues)}|{len(self.warnings)}|"
            f"{self.requires_approval}|{self.requires_dual_control}"
        )
        return hashlib.sha3_256(content.encode()).hexdigest()

    def __post_init__(self):
        if self.cryptographic_hash and self.cryptographic_hash != self.compute_hash():
            raise ValueError("Cryptographic hash mismatch")

    def to_dict(self) -> dict[str, Any]:
        return {
            "validation_id": str(self.validation_id),
            "is_valid": self.is_valid,
            "issues": [i.to_dict() for i in self.issues],
            "warnings": [i.to_dict() for i in self.warnings],
            "requires_approval": self.requires_approval,
            "requires_dual_control": self.requires_dual_control,
            "validated_at": self.validated_at.isoformat(),
            "validated_by": self.validated_by,
        }


# === 2. REALITY VALIDATION SERVICE ===


class RealityValidationService:
    """
    Service untuk memvalidasi event ekonomi.

    Business context: Memastikan bahwa hanya event yang valid dan
    memenuhi persyaratan bisnis yang dapat direkam ke sistem.
    """

    _instance: RealityValidationService | None = None
    _lock = threading.Lock()

    def __new__(cls) -> RealityValidationService:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._event_service = get_economic_event_service()
        self._obligation_service = get_financial_obligation_service()
        self._entitlement_service = get_financial_entitlement_service()
        self._validation_history: list[ValidationResult] = []
        self._max_history = 10000

    async def validate_event(
        self,
        event: EconomicEvent,
        user_id: str | None = None,
    ) -> ValidationResult:
        """
        Memvalidasi economic event.

        Args:
            event: Economic event yang akan divalidasi
            user_id: User yang melakukan validasi

        Returns:
            ValidationResult
        """
        if user_id is None:
            user_id = _get_current_user() or "unknown"

        issues = []
        warnings = []

        # 1. Basic validation
        basic_issues, basic_warnings = await self._validate_basic(event)
        issues.extend(basic_issues)
        warnings.extend(basic_warnings)

        # 2. Business rule validation
        business_issues, business_warnings = await self._validate_business_rules(event)
        issues.extend(business_issues)
        warnings.extend(business_warnings)

        # 3. Consistency validation (with related events)
        consistency_issues, consistency_warnings = await self._validate_consistency(event)
        issues.extend(consistency_issues)
        warnings.extend(consistency_warnings)

        # 4. Compliance validation
        compliance_issues, compliance_warnings = await self._validate_compliance(event)
        issues.extend(compliance_issues)
        warnings.extend(compliance_warnings)

        # Check if requires approval
        requires_approval = self._check_requires_approval(event)
        requires_dual_control = self._check_requires_dual_control(event)

        is_valid = len([i for i in issues if i.severity == ValidationSeverity.ERROR]) == 0

        result = ValidationResult(
            is_valid=is_valid,
            issues=[i for i in issues if i.severity == ValidationSeverity.ERROR],
            warnings=warnings,
            requires_approval=requires_approval,
            requires_dual_control=requires_dual_control,
            validated_by=user_id,
            cryptographic_hash="",
        )
        result.cryptographic_hash = result.compute_hash()

        # Record history
        self._validation_history.append(result)
        if len(self._validation_history) > self._max_history:
            self._validation_history = self._validation_history[-self._max_history :]

        if not is_valid:
            logger.warning(f"Event {event.event_id} validation failed: {len(issues)} error(s)")
        else:
            logger.info(f"Event {event.event_id} validation passed")

        return result

    async def _validate_basic(
        self, event: EconomicEvent
    ) -> tuple[list[ValidationIssue], list[ValidationIssue]]:
        """Validasi dasar event."""
        issues = []
        warnings = []

        # Check amount
        if event.amount:
            if event.amount.amount <= 0:
                issues.append(
                    ValidationIssue(
                        field="amount",
                        message="Amount must be greater than 0",
                        severity=ValidationSeverity.ERROR,
                        code="AMOUNT_POSITIVE",
                    )
                )
            if not event.amount.currency:
                issues.append(
                    ValidationIssue(
                        field="currency",
                        message="Currency is required",
                        severity=ValidationSeverity.ERROR,
                        code="CURRENCY_REQUIRED",
                    )
                )

        # Check date
        if event.event_date > datetime.now(UTC):
            days_future = (event.event_date - datetime.now(UTC)).days
            if days_future > 7:
                issues.append(
                    ValidationIssue(
                        field="event_date",
                        message=f"Event date is {days_future} days in the future. Future dating limit is 7 days.",
                        severity=ValidationSeverity.ERROR,
                        code="DATE_FUTURE_LIMIT",
                    )
                )
            else:
                warnings.append(
                    ValidationIssue(
                        field="event_date",
                        message=f"Event date is {days_future} days in the future",
                        severity=ValidationSeverity.WARNING,
                        code="DATE_FUTURE_WARNING",
                    )
                )

        # Check description
        if not event.description or len(event.description.strip()) < 3:
            issues.append(
                ValidationIssue(
                    field="description",
                    message="Description is required (minimum 3 characters)",
                    severity=ValidationSeverity.ERROR,
                    code="DESCRIPTION_REQUIRED",
                )
            )

        # Check source document for material events (combined condition)
        if (event.amount and event.amount.amount > Decimal("10000000")
                and not event.source_document_ref):  # > 10 juta
            warnings.append(
                ValidationIssue(
                    field="source_document_ref",
                    message="Source document reference is recommended for material events (> 10 million)",
                    severity=ValidationSeverity.WARNING,
                    code="SOURCE_DOC_RECOMMENDED",
                )
            )

        # Check counterparty for certain event types (combined condition)
        if (event.event_type in (
            EconomicEventType.SALE_OF_GOODS,
            EconomicEventType.SALE_OF_SERVICES,
            EconomicEventType.PURCHASE_OF_GOODS,
            EconomicEventType.PURCHASE_OF_SERVICES,
        ) and not event.counterparty_id):
            issues.append(
                ValidationIssue(
                    field="counterparty_id",
                    message="Counterparty is required for this event type",
                    severity=ValidationSeverity.ERROR,
                    code="COUNTERPARTY_REQUIRED",
                )
            )

        return issues, warnings

    async def _validate_business_rules(
        self,
        event: EconomicEvent,
    ) -> tuple[list[ValidationIssue], list[ValidationIssue]]:
        """Validasi aturan bisnis spesifik per event type."""
        issues = []
        warnings = []

        # Sale of goods
        if event.event_type == EconomicEventType.SALE_OF_GOODS:
            if not event.quantity:
                warnings.append(
                    ValidationIssue(
                        field="quantity",
                        message="Quantity is recommended for sale of goods",
                        severity=ValidationSeverity.WARNING,
                        code="QUANTITY_RECOMMENDED",
                    )
                )
            # Check if price is reasonable (prevent typos)
            if event.amount and event.quantity and event.quantity.value > 0:
                unit_price = event.amount.amount / Decimal(str(event.quantity.value))
                if unit_price > Decimal("10000000"):  # > 10 juta per unit
                    warnings.append(
                        ValidationIssue(
                            field="amount",
                            message=f"Unit price {unit_price:,.0f} is unusually high. Please verify.",
                            severity=ValidationSeverity.WARNING,
                            code="HIGH_UNIT_PRICE",
                        )
                    )

        # Purchase of goods
        elif event.event_type == EconomicEventType.PURCHASE_OF_GOODS:
            if not event.quantity:
                warnings.append(
                    ValidationIssue(
                        field="quantity",
                        message="Quantity is recommended for purchase of goods",
                        severity=ValidationSeverity.WARNING,
                        code="QUANTITY_RECOMMENDED",
                    )
                )

        # Asset acquisition
        elif event.event_type == EconomicEventType.ASSET_ACQUISITION:
            if not event.metadata.get("asset_type"):
                warnings.append(
                    ValidationIssue(
                        field="metadata.asset_type",
                        message="Asset type is recommended for asset acquisition",
                        severity=ValidationSeverity.WARNING,
                        code="ASSET_TYPE_RECOMMENDED",
                    )
                )

        # Salary expense
        elif event.event_type == EconomicEventType.SALARY_EXPENSE:
            if not event.metadata.get("employee_count"):
                warnings.append(
                    ValidationIssue(
                        field="metadata.employee_count",
                        message="Employee count is recommended for salary expense",
                        severity=ValidationSeverity.WARNING,
                        code="EMPLOYEE_COUNT_RECOMMENDED",
                    )
                )
            if event.amount and event.amount.amount > Decimal("500000000"):  # > 500 juta
                warnings.append(
                    ValidationIssue(
                        field="amount",
                        message=f"Salary expense {event.amount.amount:,.0f} is unusually high. Please verify.",
                        severity=ValidationSeverity.WARNING,
                        code="HIGH_SALARY_AMOUNT",
                    )
                )

        # Loan drawdown
        elif event.event_type == EconomicEventType.LOAN_DRAWDOWN:
            if not event.metadata.get("loan_agreement_ref"):
                warnings.append(
                    ValidationIssue(
                        field="metadata.loan_agreement_ref",
                        message="Loan agreement reference is recommended",
                        severity=ValidationSeverity.WARNING,
                        code="LOAN_AGREEMENT_RECOMMENDED",
                    )
                )

        return issues, warnings

    async def _validate_consistency(
        self,
        event: EconomicEvent,
    ) -> tuple[list[ValidationIssue], list[ValidationIssue]]:
        """Validasi konsistensi dengan event terkait."""
        issues = []
        warnings = []

        # Check for duplicate (same source document)
        if event.source_document_ref:
            existing_events = self._event_service.get_events_by_type(
                legal_entity_id=event.legal_entity_id,
                event_type=event.event_type,
            )
            for existing in existing_events:
                if existing.source_document_ref == event.source_document_ref:
                    # If same event ID, it's the same event (update)
                    if existing.event_id != event.event_id:
                        warnings.append(
                            ValidationIssue(
                                field="source_document_ref",
                                message=f"Event with same source document already exists: {existing.event_id}",
                                severity=ValidationSeverity.WARNING,
                                code="DUPLICATE_SOURCE_DOC",
                            )
                        )
                    break

        # Check reversal consistency
        if event.reversal_of:
            original = self._event_service.get_event(event.reversal_of)
            if not original:
                issues.append(
                    ValidationIssue(
                        field="reversal_of",
                        message=f"Original event {event.reversal_of} not found",
                        severity=ValidationSeverity.ERROR,
                        code="ORIGINAL_EVENT_NOT_FOUND",
                    )
                )
            elif original.status != EconomicEventStatus.POSTED:
                issues.append(
                    ValidationIssue(
                        field="reversal_of",
                        message=f"Original event {event.reversal_of} status is {original.status.name}, must be POSTED to reverse",
                        severity=ValidationSeverity.ERROR,
                        code="ORIGINAL_EVENT_NOT_POSTED",
                    )
                )

        return issues, warnings

    async def _validate_compliance(
        self,
        event: EconomicEvent,
    ) -> tuple[list[ValidationIssue], list[ValidationIssue]]:
        """Validasi kepatuhan terhadap regulasi."""
        issues = []
        warnings = []

        # Check for large cash transactions (AML) - combined condition
        if (event.amount and event.amount.amount > Decimal("100000000")
                and event.metadata.get("payment_method") == "CASH"):  # > 100 juta
            issues.append(
                ValidationIssue(
                    field="payment_method",
                    message="Large cash transaction (>100M) requires enhanced due diligence per AML regulations",
                    severity=ValidationSeverity.ERROR,
                    code="AML_LARGE_CASH",
                )
            )

        # Check for related party transactions
        if event.metadata.get("is_related_party"):
            if not event.metadata.get("arm_length_price"):
                warnings.append(
                    ValidationIssue(
                        field="metadata.arm_length_price",
                        message="Related party transaction requires arm's length price documentation",
                        severity=ValidationSeverity.WARNING,
                        code="RELATED_PARTY_ARM_LENGTH",
                    )
                )
            if event.amount and event.amount.amount > Decimal("50000000"):  # > 50 juta
                warnings.append(
                    ValidationIssue(
                        field="amount",
                        message=f"Large related party transaction {event.amount.amount:,.0f} may require board approval",
                        severity=ValidationSeverity.WARNING,
                        code="RELATED_PARTY_LARGE",
                    )
                )

        # Check for cross-border transactions - combined condition
        if (event.metadata.get("is_cross_border")
                and not event.metadata.get("exchange_rate_used")):
            warnings.append(
                ValidationIssue(
                    field="metadata.exchange_rate_used",
                    message="Exchange rate is required for cross-border transactions",
                    severity=ValidationSeverity.WARNING,
                    code="CROSS_BORDER_EXCHANGE_RATE",
                )
            )

        return issues, warnings

    def _check_requires_approval(self, event: EconomicEvent) -> bool:
        """Memeriksa apakah event memerlukan approval."""
        # Large amount requires approval
        if event.amount and event.amount.amount > Decimal("50000000"):  # > 50 juta
            return True

        # Certain event types require approval
        approval_types = [
            EconomicEventType.ASSET_DISPOSAL,
            EconomicEventType.ASSET_IMPAIRMENT,
            EconomicEventType.ASSET_REVALUATION,
            EconomicEventType.PERIOD_CLOSE,
            EconomicEventType.PERIOD_ADJUSTMENT,
            EconomicEventType.BAD_DEBT_WRITE_OFF,
        ]

        if event.event_type in approval_types:
            return True

        # Related party transactions above threshold require approval - return condition directly
        return (event.metadata.get("is_related_party") and event.amount
                and event.amount.amount > Decimal("25000000"))  # > 25 juta

    def _check_requires_dual_control(self, event: EconomicEvent) -> bool:
        """Memeriksa apakah event memerlukan dual control."""
        # Very large amount requires dual control
        if event.amount and event.amount.amount > Decimal("1000000000"):  # > 1 Miliar
            return True

        # Critical event types require dual control
        dual_control_types = [
            EconomicEventType.ASSET_DISPOSAL,
            EconomicEventType.PERIOD_CLOSE,
            EconomicEventType.ASSET_IMPAIRMENT,
            EconomicEventType.ASSET_REVALUATION,
            EconomicEventType.BAD_DEBT_WRITE_OFF,
        ]

        # Return condition directly (SIM103)
        return event.event_type in dual_control_types

    async def validate_before_posting(
        self,
        event_id: UUID,
        user_id: str | None = None,
    ) -> ValidationResult:
        """
        Memvalidasi event sebelum diposting.

        Args:
            event_id: ID event
            user_id: User yang memposting

        Returns:
            ValidationResult
        """
        event = self._event_service.get_event(event_id)
        if not event:
            return ValidationResult(
                is_valid=False,
                issues=[
                    ValidationIssue(
                        field="event_id",
                        message=f"Event {event_id} not found",
                        severity=ValidationSeverity.ERROR,
                        code="EVENT_NOT_FOUND",
                    )
                ],
                warnings=[],
                validated_by=user_id or "system",
            )

        return await self.validate_event(event, user_id)

    def get_validation_history(
        self,
        limit: int = 100,
        event_id: UUID | None = None,
        only_failed: bool = False,
    ) -> list[ValidationResult]:
        """Mendapatkan history validasi."""
        with self._lock:
            results = self._validation_history[-limit:]
        if event_id:
            # Filter by event_id requires looking up the original event
            # Simplified: assume validation_result contains event_id in metadata
            results = [r for r in results if r.validated_by]  # Placeholder
        if only_failed:
            results = [r for r in results if not r.is_valid]
        return results

    def get_statistics(self) -> dict[str, Any]:
        """Mendapatkan statistik validasi."""
        with self._lock:
            total = len(self._validation_history)
            if total == 0:
                return {"total_validations": 0}

            passed = len([r for r in self._validation_history if r.is_valid])
            failed = total - passed

            # Count issues by code
            issue_codes = {}
            for r in self._validation_history:
                for i in r.issues:
                    if i.code:
                        issue_codes[i.code] = issue_codes.get(i.code, 0) + 1

            return {
                "total_validations": total,
                "passed": passed,
                "failed": failed,
                "pass_rate": passed / total if total > 0 else 0,
                "issue_codes": issue_codes,
                "requires_approval_count": len(
                    [r for r in self._validation_history if r.requires_approval]
                ),
                "requires_dual_control_count": len(
                    [r for r in self._validation_history if r.requires_dual_control]
                ),
                "latest_validation": self._validation_history[-1].validated_at.isoformat()
                if self._validation_history
                else None,
            }

    def reset(self) -> None:
        """Reset service (untuk testing)."""
        with self._lock:
            self._validation_history = []


# === 3. SINGLETON ACCESSOR ===

_reality_validation_service_instance: RealityValidationService | None = None


def get_reality_validation_service() -> RealityValidationService:
    """Mendapatkan instance singleton RealityValidationService."""
    global _reality_validation_service_instance
    if _reality_validation_service_instance is None:
        _reality_validation_service_instance = RealityValidationService()
    return _reality_validation_service_instance


# === 4. EXPORTS ===

__all__ = [
    "RealityValidationService",
    "ValidationIssue",
    "ValidationResult",
    "ValidationSeverity",
    "get_reality_validation_service",
]
