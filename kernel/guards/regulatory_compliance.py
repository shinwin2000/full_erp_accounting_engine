#!/usr/bin/env python3
"""
Module: regulatory_compliance.py
Layer: 4 - Kernel / Guards
Responsibility: Guard untuk kepatuhan regulasi spesifik (OJK, BI, DJP).
               Memastikan bahwa transaksi mematuhi aturan regulasi yang berlaku,
               seperti batasan transaksi mata uang asing, pelaporan ke OJK,
               kepatuhan anti pencucian uang (AML), dan ketentuan perpajakan.

Dependencies:
- standard library (logging, datetime, decimal, typing, threading, hashlib)
- kernel.context_holder (get_current_legal_entity, get_current_user)
- kernel.guards.guard_exceptions (GuardViolationError, RegulatoryComplianceError, GuardSeverity)

Audit: Setiap pelanggaran regulasi dictat untuk pelaporan ke regulator.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from kernel.context_holder import get_current_legal_entity, get_current_user
from kernel.guards.guard_exceptions import (
    GuardSeverity,
    RegulatoryComplianceError,
)

logger = logging.getLogger(__name__)


# === 1. FALLBACK REGULATORY CONFIG PORT (internal, tidak mengimpor adapters/infrastructure) ===


class _FallbackRegulatoryConfig:
    """Fallback regulatory config jika infrastructure belum tersedia.
    Menyimpan konfigurasi regulasi dalam memory.
    """

    def __init__(self):
        self._config: dict[str, Any] = {
            "fx_limit_usd": 1000000,
            "fx_limit_eur": 1100000,
            "fx_reporting_threshold_usd": 100000,
            "aml_threshold_idr": 100000000,
            "aml_lookback_days": 7,
            "aml_small_transaction_threshold": 90000000,
            "aml_max_small_transactions": 5,
            "transfer_pricing_tolerance_percent": 5,
            "tax_pph23_rates": {"service": 2, "rental": 4, "construction": 3},
            "tax_pph26_rate": 20,
            "tax_invoice_threshold": 1000000,
            "ojk_reporting_threshold": 5000000000,
            "bi_fx_reporting_enabled": True,
            "corporate_action_approval_required": True,
        }

    async def get_config(self, key: str, default: Any = None) -> Any:
        """Mendapatkan nilai konfigurasi."""
        return self._config.get(key, default)

    async def set_config(self, key: str, value: Any) -> None:
        """Mengatur nilai konfigurasi."""
        self._config[key] = value

    async def get_all_config(self) -> dict[str, Any]:
        """Mendapatkan semua konfigurasi."""
        return self._config.copy()


# === 2. CONSTANTS & ENUMS ===


class RegulatoryDomain(Enum):
    """Domain regulasi."""

    FOREIGN_EXCHANGE = "foreign_exchange"  # Bank Indonesia / OJK
    ANTI_MONEY_LAUNDERING = "aml"  # PP TPPU
    TAX_COMPLIANCE = "tax"  # DJP
    CORPORATE_GOVERNANCE = "governance"  # OJK
    CAPITAL_MARKET = "capital_market"  # OJK for listed companies
    DATA_PRIVACY = "privacy"  # PDP Law
    TRANSFER_PRICING = "transfer_pricing"  # DJP
    ENVIRONMENTAL = "environmental"  # ESG / OJK
    LABOR = "labor"  # Depnaker


class ComplianceSeverity(Enum):
    """Severity pelanggaran regulasi."""

    CRITICAL = 80  # Potensi pidana / denda besar
    HIGH = 60  # Pelanggaran material, perlu pelaporan
    MEDIUM = 40  # Ketidaksesuaian prosedur
    LOW = 20  # Minor, dapat diperbaiki
    INFO = 0


@dataclass
class RegulatoryRule:
    """Definisi aturan regulasi."""

    rule_id: str
    domain: RegulatoryDomain
    description: str
    severity: ComplianceSeverity
    is_active: bool = True
    parameters: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str = "system"
    modified_at: datetime | None = None
    modified_by: str | None = None
    cryptographic_hash: str = ""

    def compute_hash(self) -> str:
        content = (
            f"{self.rule_id}|{self.domain.value}|{self.severity.value}|{self.description[:100]}"
        )
        return hashlib.sha3_256(content.encode()).hexdigest()

    def __post_init__(self):
        if self.cryptographic_hash and self.cryptographic_hash != self.compute_hash():
            raise ValueError("Cryptographic hash mismatch")

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "domain": self.domain.value,
            "description": self.description,
            "severity": self.severity.name,
            "is_active": self.is_active,
            "parameters": self.parameters,
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
        }


@dataclass
class ComplianceViolation:
    """Rekaman pelanggaran regulasi."""

    violation_id: UUID
    rule_id: str
    domain: RegulatoryDomain
    severity: ComplianceSeverity
    transaction_id: UUID | None
    legal_entity_id: UUID | None
    user_id: str | None
    amount: Decimal | None
    currency: str | None
    message: str
    details: dict[str, Any]
    detected_at: datetime
    is_resolved: bool = False
    resolved_at: datetime | None = None
    resolved_by: str | None = None
    resolution_action: str | None = None
    report_sent_to_regulator: bool = False
    report_sent_at: datetime | None = None
    cryptographic_hash: str = ""

    def compute_hash(self) -> str:
        content = (
            f"{self.violation_id}|{self.rule_id}|{self.domain.value}|{self.severity.value}|"
            f"{self.transaction_id}|{self.message[:100]}"
        )
        return hashlib.sha3_256(content.encode()).hexdigest()

    def __post_init__(self):
        if self.cryptographic_hash and self.cryptographic_hash != self.compute_hash():
            raise ValueError("Cryptographic hash mismatch")

    def resolve(self, resolved_by: str, action: str) -> ComplianceViolation:
        """Menandai pelanggaran sebagai resolved."""
        return ComplianceViolation(
            violation_id=self.violation_id,
            rule_id=self.rule_id,
            domain=self.domain,
            severity=self.severity,
            transaction_id=self.transaction_id,
            legal_entity_id=self.legal_entity_id,
            user_id=self.user_id,
            amount=self.amount,
            currency=self.currency,
            message=self.message,
            details=self.details,
            detected_at=self.detected_at,
            is_resolved=True,
            resolved_at=datetime.now(UTC),
            resolved_by=resolved_by,
            resolution_action=action,
            report_sent_to_regulator=self.report_sent_to_regulator,
            report_sent_at=self.report_sent_at,
            cryptographic_hash=self.cryptographic_hash,
        )

    def mark_report_sent(self, sent_by: str) -> ComplianceViolation:
        """Menandai bahwa laporan telah dikirim ke regulator."""
        return ComplianceViolation(
            violation_id=self.violation_id,
            rule_id=self.rule_id,
            domain=self.domain,
            severity=self.severity,
            transaction_id=self.transaction_id,
            legal_entity_id=self.legal_entity_id,
            user_id=self.user_id,
            amount=self.amount,
            currency=self.currency,
            message=self.message,
            details=self.details,
            detected_at=self.detected_at,
            is_resolved=self.is_resolved,
            resolved_at=self.resolved_at,
            resolved_by=self.resolved_by,
            resolution_action=self.resolution_action,
            report_sent_to_regulator=True,
            report_sent_at=datetime.now(UTC),
            cryptographic_hash=self.cryptographic_hash,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "violation_id": str(self.violation_id),
            "rule_id": self.rule_id,
            "domain": self.domain.value,
            "severity": self.severity.name,
            "transaction_id": str(self.transaction_id) if self.transaction_id else None,
            "legal_entity_id": str(self.legal_entity_id) if self.legal_entity_id else None,
            "user_id": self.user_id,
            "amount": str(self.amount) if self.amount else None,
            "currency": self.currency,
            "message": self.message,
            "detected_at": self.detected_at.isoformat(),
            "is_resolved": self.is_resolved,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "resolved_by": self.resolved_by,
            "report_sent_to_regulator": self.report_sent_to_regulator,
        }


# === 3. DEFAULT REGULATORY RULES ===

DEFAULT_REGULATORY_RULES: list[RegulatoryRule] = [
    RegulatoryRule(
        rule_id="FX_LIMIT_IDR",
        domain=RegulatoryDomain.FOREIGN_EXCHANGE,
        description="Foreign currency transaction limit for IDR. Maximum USD 1,000,000 equivalent per day without license.",
        severity=ComplianceSeverity.HIGH,
        parameters={"max_usd_equivalent": 1000000, "currency": "USD", "period": "day"},
    ),
    RegulatoryRule(
        rule_id="AML_THRESHOLD",
        domain=RegulatoryDomain.ANTI_MONEY_LAUNDERING,
        description="Transaction above IDR 100,000,000 requires enhanced due diligence.",
        severity=ComplianceSeverity.CRITICAL,
        parameters={"threshold_idr": 100000000},
    ),
    RegulatoryRule(
        rule_id="AML_STRUCTURING",
        domain=RegulatoryDomain.ANTI_MONEY_LAUNDERING,
        description="Multiple small transactions just below threshold (structuring) is prohibited.",
        severity=ComplianceSeverity.CRITICAL,
        parameters={"lookback_days": 7, "small_transaction_threshold": 90000000, "max_count": 5},
    ),
    RegulatoryRule(
        rule_id="TAX_WITHHOLDING_PPH23",
        domain=RegulatoryDomain.TAX_COMPLIANCE,
        description="PPh 23 withholding (2% / 4% / etc.) must be applied for services and rental.",
        severity=ComplianceSeverity.HIGH,
        parameters={
            "applicable_transactions": ["SERVICE_PAYMENT", "RENTAL_PAYMENT", "CONSTRUCTION_PAYMENT"]
        },
    ),
    RegulatoryRule(
        rule_id="TAX_WITHHOLDING_PPH26",
        domain=RegulatoryDomain.TAX_COMPLIANCE,
        description="PPh 26 withholding (20%) for foreign parties.",
        severity=ComplianceSeverity.HIGH,
        parameters={"rate": 0.20},
    ),
    RegulatoryRule(
        rule_id="TAX_INVOICE_PPK",
        domain=RegulatoryDomain.TAX_COMPLIANCE,
        description="Tax invoice required for PKP transactions above IDR 1,000,000.",
        severity=ComplianceSeverity.MEDIUM,
        parameters={"threshold_idr": 1000000},
    ),
    RegulatoryRule(
        rule_id="TRANSFER_PRICING_ARM_LENGTH",
        domain=RegulatoryDomain.TRANSFER_PRICING,
        description="Intercompany transactions must be at arm's length price.",
        severity=ComplianceSeverity.HIGH,
        parameters={"tolerance_percent": 5},
    ),
    RegulatoryRule(
        rule_id="DATA_PRIVACY_CONSENT",
        domain=RegulatoryDomain.DATA_PRIVACY,
        description="Customer data processing requires consent.",
        severity=ComplianceSeverity.CRITICAL,
        parameters={},
    ),
    RegulatoryRule(
        rule_id="FX_REPORTING",
        domain=RegulatoryDomain.FOREIGN_EXCHANGE,
        description="Foreign exchange transactions above USD 100,000 must be reported to BI.",
        severity=ComplianceSeverity.MEDIUM,
        parameters={"reporting_threshold_usd": 100000},
    ),
    RegulatoryRule(
        rule_id="CORPORATE_ACTION_APPROVAL",
        domain=RegulatoryDomain.CORPORATE_GOVERNANCE,
        description="Corporate actions (dividend, merger, etc.) require board approval.",
        severity=ComplianceSeverity.HIGH,
        parameters={"requires_approval": True},
    ),
    RegulatoryRule(
        rule_id="ESG_CARBON_REPORTING",
        domain=RegulatoryDomain.ENVIRONMENTAL,
        description="Carbon emission reporting required for certain industries.",
        severity=ComplianceSeverity.MEDIUM,
        parameters={"threshold_co2_tons": 1000},
    ),
]


# ============================================================================
# BASE REGULATORY COMPLIANCE GUARD (ABSTRACT)
# ============================================================================

class BaseRegulatoryComplianceGuard(ABC):
    """Base contract untuk Regulatory Compliance Guard."""

    @abstractmethod
    def enable(self, enabled: bool = True) -> None:
        """Mengaktifkan atau menonaktifkan guard."""
        pass

    @abstractmethod
    def register_rule(self, rule: RegulatoryRule) -> None:
        """Mendaftarkan aturan regulasi baru."""
        pass

    @abstractmethod
    def get_rule(self, rule_id: str) -> RegulatoryRule | None:
        """Mendapatkan aturan regulasi berdasarkan ID."""
        pass

    @abstractmethod
    def get_all_rules(self, active_only: bool = True) -> list[RegulatoryRule]:
        """Mendapatkan semua aturan regulasi."""
        pass

    @abstractmethod
    def update_rule_status(self, rule_id: str, is_active: bool, updated_by: str) -> bool:
        """Mengaktifkan/menonaktifkan aturan regulasi."""
        pass

    @abstractmethod
    async def enforce(
        self,
        checks: list[tuple[str, dict[str, Any]]],
        legal_entity_id: UUID | None = None,
        user_id: str | None = None,
        raise_on_violation: bool = True,
    ) -> tuple[bool, list[ComplianceViolation]]:
        """Menjalankan serangkaian pemeriksaan regulasi."""
        pass

    @abstractmethod
    def check(self, context: dict) -> list[str]:
        """Sync check method untuk compliance checker."""
        pass

    @abstractmethod
    def get_violations(
        self,
        limit: int = 100,
        domain: RegulatoryDomain | None = None,
        unresolved_only: bool = False,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[ComplianceViolation]:
        """Mendapatkan history pelanggaran regulasi."""
        pass

    @abstractmethod
    def resolve_violation(
        self,
        violation_id: UUID,
        resolved_by: str,
        resolution_action: str,
    ) -> ComplianceViolation | None:
        """Menandai pelanggaran sebagai resolved."""
        pass

    @abstractmethod
    def get_statistics(self) -> dict[str, Any]:
        """Mendapatkan statistik kepatuhan regulasi."""
        pass

    @abstractmethod
    def reset(self) -> None:
        """Reset guard (untuk testing)."""
        pass

    # === Entity methods (wajib untuk semua guard) ===
    @abstractmethod
    def validate(self) -> dict[str, Any]:
        """Validasi internal state."""
        pass

    @abstractmethod
    def to_dict(self) -> dict[str, Any]:
        """Konversi ke dictionary."""
        pass

    @classmethod
    @abstractmethod
    def from_dict(cls, data: dict[str, Any]) -> BaseRegulatoryComplianceGuard:
        """Reconstruct dari dictionary."""
        pass

    @abstractmethod
    def clone(self) -> BaseRegulatoryComplianceGuard:
        """Clone instance."""
        pass

    @abstractmethod
    def snapshot(self) -> dict[str, Any]:
        """Ambil snapshot state."""
        pass

    @abstractmethod
    def version(self) -> int:
        """Dapatkan versi."""
        pass

    @abstractmethod
    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        """Dapatkan audit trail."""
        pass

    @abstractmethod
    def touch(self, touched_by: str) -> BaseRegulatoryComplianceGuard:
        """Touch instance (increment version)."""
        pass


# ============================================================================
# REGULATORY COMPLIANCE GUARD (CONCRETE)
# ============================================================================

class RegulatoryComplianceGuard(BaseRegulatoryComplianceGuard):
    """
    Guard untuk kepatuhan regulasi.

    Business context: Memastikan bahwa transaksi mematuhi berbagai regulasi
    yang berlaku (OJK, BI, DJP, AML, dll). Mencegah denda dan sanksi
    akibat ketidakpatuhan.
    """

    def __init__(self, regulatory_config: Any | None = None):
        self._config = regulatory_config or _FallbackRegulatoryConfig()
        self._rules: dict[str, RegulatoryRule] = {r.rule_id: r for r in DEFAULT_REGULATORY_RULES}
        self._violations: list[ComplianceViolation] = []
        self._transaction_history: dict[
            UUID, list[dict[str, Any]]
        ] = {}  # customer_id -> recent transactions
        self._max_history = 10000
        self._lock = threading.RLock()
        self._enabled = True
        self._report_violations_to_regulator = False  # Simulate sending reports
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []

    # ==================== SYNC CHECK METHOD (untuk checker compliance) ====================

    def check(self, context: dict) -> list[str]:
        """
        Sync check method untuk compliance checker.
        Memvalidasi context dan mengembalikan daftar error jika ada.
        """
        errors = []
        checks = context.get("checks")
        if not checks:
            errors.append("checks list is required")
        elif not isinstance(checks, list):
            errors.append("checks must be a list of tuples")
        else:
            for i, check in enumerate(checks):
                if not isinstance(check, (tuple, list)) or len(check) != 2:
                    errors.append(f"check[{i}] must be a tuple of (check_name, params)")
                else:
                    check_name, params = check
                    if not check_name:
                        errors.append(f"check[{i}] check_name is empty")
                    if not isinstance(params, dict):
                        errors.append(f"check[{i}] params must be a dict")
        return errors

    # ==================== ENTITY METHODS (wajib) ====================

    def validate(self) -> dict[str, Any]:
        """Validasi internal state."""
        errors = []
        if self._max_history <= 0:
            errors.append("max_history must be positive")
        if not self._rules:
            errors.append("No rules registered")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        """Konversi ke dictionary."""
        return {
            "enabled": self._enabled,
            "rules_count": len(self._rules),
            "active_rules": len([r for r in self._rules.values() if r.is_active]),
            "max_history": self._max_history,
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RegulatoryComplianceGuard:
        """Reconstruct dari dictionary."""
        instance = cls()
        instance._enabled = data.get("enabled", True)
        instance._max_history = data.get("max_history", 10000)
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> RegulatoryComplianceGuard:
        """Clone instance."""
        new_instance = RegulatoryComplianceGuard()
        new_instance._enabled = self._enabled
        new_instance._max_history = self._max_history
        new_instance._version = self._version + 1
        return new_instance

    def snapshot(self) -> dict[str, Any]:
        """Ambil snapshot state."""
        with self._lock:
            return {
                "version": self._version,
                "violations_count": len(self._violations),
                "enabled": self._enabled,
                "timestamp": datetime.now(UTC).isoformat(),
            }

    def version(self) -> int:
        """Dapatkan versi."""
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        """Dapatkan audit trail."""
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> RegulatoryComplianceGuard:
        """Touch instance (increment version)."""
        self._version += 1
        self._audit_trail.append({
            "action": "TOUCH",
            "performed_by": touched_by,
            "timestamp": datetime.now(UTC).isoformat(),
            "version": self._version,
        })
        return self

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]) -> None:
        self._audit_trail.append({
            "action": action,
            "performed_by": performed_by,
            "timestamp": datetime.now(UTC).isoformat(),
            "version": self._version,
            "details": details,
        })

    # ==================== ORIGINAL BUSINESS METHODS ====================

    def enable(self, enabled: bool = True) -> None:
        """Mengaktifkan atau menonaktifkan guard."""
        self._enabled = enabled
        self._record_audit("ENABLE", "system", {"enabled": enabled})
        logger.info(f"Regulatory compliance guard enabled: {enabled}")

    def register_rule(self, rule: RegulatoryRule) -> None:
        """Mendaftarkan aturan regulasi baru."""
        rule = RegulatoryRule(
            rule_id=rule.rule_id,
            domain=rule.domain,
            description=rule.description,
            severity=rule.severity,
            is_active=rule.is_active,
            parameters=rule.parameters.copy(),
            created_at=rule.created_at,
            created_by=rule.created_by,
            cryptographic_hash="",
        )
        rule = RegulatoryRule(**{**rule.__dict__, "cryptographic_hash": rule.compute_hash()})
        with self._lock:
            self._rules[rule.rule_id] = rule
        self._record_audit("REGISTER_RULE", "system", {"rule_id": rule.rule_id})
        logger.info(f"Registered regulatory rule: {rule.rule_id}")

    def get_rule(self, rule_id: str) -> RegulatoryRule | None:
        """Mendapatkan aturan regulasi berdasarkan ID."""
        return self._rules.get(rule_id)

    def get_all_rules(self, active_only: bool = True) -> list[RegulatoryRule]:
        """Mendapatkan semua aturan regulasi."""
        with self._lock:
            rules = list(self._rules.values())
        if active_only:
            rules = [r for r in rules if r.is_active]
        return rules

    def update_rule_status(self, rule_id: str, is_active: bool, updated_by: str) -> bool:
        """Mengaktifkan/menonaktifkan aturan regulasi."""
        with self._lock:
            if rule_id in self._rules:
                old = self._rules[rule_id]
                new_rule = RegulatoryRule(
                    rule_id=old.rule_id,
                    domain=old.domain,
                    description=old.description,
                    severity=old.severity,
                    is_active=is_active,
                    parameters=old.parameters.copy(),
                    created_at=old.created_at,
                    created_by=old.created_by,
                    modified_at=datetime.now(UTC),
                    modified_by=updated_by,
                    cryptographic_hash=old.cryptographic_hash,
                )
                new_rule = RegulatoryRule(
                    **{**new_rule.__dict__, "cryptographic_hash": new_rule.compute_hash()}
                )
                self._rules[rule_id] = new_rule
                self._record_audit("UPDATE_RULE", updated_by, {"rule_id": rule_id, "is_active": is_active})
                logger.info(
                    f"Regulatory rule {rule_id} active status set to {is_active} by {updated_by}"
                )
                return True
        return False

    async def check_foreign_exchange_limit(
        self,
        amount: Decimal,
        currency: str,
        legal_entity_id: UUID | None = None,
        transaction_id: UUID | None = None,
        user_id: str | None = None,
    ) -> tuple[bool, ComplianceViolation | None]:
        """
        Memeriksa batasan transaksi valas.

        Returns:
            (is_compliant, violation_if_any)
        """
        rule = self._rules.get("FX_LIMIT_IDR")
        if not rule or not rule.is_active:
            return True, None

        # Get limit from config
        max_usd = Decimal(str(await self._config.get_config("fx_limit_usd", 1000000)))
        fx_reporting_threshold = Decimal(
            str(await self._config.get_config("fx_reporting_threshold_usd", 100000))
        )

        # Simplified conversion: assume amount is in USD or need conversion
        # In production, would use exchange rate
        if currency.upper() != "USD":
            # For now, warn but not block
            logger.warning(
                f"Foreign currency {currency} transaction of {amount} needs FX limit check"
            )

        if amount > max_usd:
            violation = self._create_violation(
                rule_id=rule.rule_id,
                domain=rule.domain,
                severity=rule.severity,
                transaction_id=transaction_id,
                legal_entity_id=legal_entity_id,
                user_id=user_id,
                amount=amount,
                currency=currency,
                message=f"Foreign currency transaction {amount} {currency} exceeds {max_usd} USD equivalent limit without license",
                details={"amount": str(amount), "currency": currency, "max_usd": str(max_usd)},
            )
            return False, violation

        # Also check reporting threshold (warning only)
        if amount > fx_reporting_threshold:
            reporting_rule = self._rules.get("FX_REPORTING")
            if reporting_rule and reporting_rule.is_active:
                # This is a warning, not a block
                logger.warning(
                    f"FX transaction {amount} {currency} exceeds reporting threshold {fx_reporting_threshold}. Reporting required."
                )

        return True, None

    async def check_aml_threshold(
        self,
        amount: Decimal,
        customer_id: UUID | None = None,
        legal_entity_id: UUID | None = None,
        transaction_id: UUID | None = None,
        user_id: str | None = None,
    ) -> tuple[bool, ComplianceViolation | None]:
        """
        Memeriksa threshold AML (Anti-Money Laundering).

        Returns:
            (is_compliant, violation_if_requires_edd)
        """
        rule = self._rules.get("AML_THRESHOLD")
        if not rule or not rule.is_active:
            return True, None

        threshold = Decimal(str(await self._config.get_config("aml_threshold_idr", 100000000)))

        if amount >= threshold:
            violation = self._create_violation(
                rule_id=rule.rule_id,
                domain=rule.domain,
                severity=rule.severity,
                transaction_id=transaction_id,
                legal_entity_id=legal_entity_id,
                user_id=user_id,
                amount=amount,
                currency="IDR",
                message=f"Transaction amount {amount} exceeds AML threshold {threshold}. Enhanced Due Diligence required.",
                details={
                    "amount": str(amount),
                    "threshold": str(threshold),
                    "customer_id": str(customer_id) if customer_id else None,
                },
            )
            return False, violation

        return True, None

    async def check_aml_structuring(
        self,
        amount: Decimal,
        customer_id: UUID,
        transaction_date: datetime,
        legal_entity_id: UUID | None = None,
        transaction_id: UUID | None = None,
        user_id: str | None = None,
    ) -> tuple[bool, ComplianceViolation | None]:
        """
        Memeriksa pola structuring (pengelompokan transaksi kecil mendekati threshold).

        Returns:
            (is_compliant, violation_if_structuring_detected)
        """
        rule = self._rules.get("AML_STRUCTURING")
        if not rule or not rule.is_active:
            return True, None

        lookback_days = await self._config.get_config("aml_lookback_days", 7)
        small_threshold = Decimal(
            str(await self._config.get_config("aml_small_transaction_threshold", 90000000))
        )
        max_count = await self._config.get_config("aml_max_small_transactions", 5)

        # Get recent transactions for this customer
        lookback_start = transaction_date - timedelta(days=lookback_days)
        recent = self._get_customer_transactions(customer_id, lookback_start, transaction_date)

        # Count small transactions just below threshold
        small_transactions = [
            t
            for t in recent
            if t.get("amount", 0) >= small_threshold and t.get("amount", 0) < Decimal(100000000)
        ]

        if len(small_transactions) >= max_count:
            total_amount = sum(t.get("amount", 0) for t in small_transactions)
            violation = self._create_violation(
                rule_id=rule.rule_id,
                domain=rule.domain,
                severity=rule.severity,
                transaction_id=transaction_id,
                legal_entity_id=legal_entity_id,
                user_id=user_id,
                amount=amount,
                currency="IDR",
                message=f"Potential structuring detected: {len(small_transactions)} transactions near threshold in {lookback_days} days, total {total_amount}",
                details={
                    "small_transactions_count": len(small_transactions),
                    "total_amount": str(total_amount),
                    "lookback_days": lookback_days,
                    "customer_id": str(customer_id),
                },
            )
            return False, violation

        return True, None

    async def check_tax_withholding(
        self,
        transaction_type: str,
        amount: Decimal,
        supplier_type: str | None = None,  # "PKP", "NON_PKP", "FOREIGN"
        is_intercompany: bool = False,
        legal_entity_id: UUID | None = None,
        transaction_id: UUID | None = None,
        user_id: str | None = None,
    ) -> tuple[bool, ComplianceViolation | None]:
        """
        Memeriksa kepatuhan pemotongan pajak (PPh).

        Returns:
            (is_compliant, violation_if_missing_withholding)
        """
        # Check PPh 23
        rule_pph23 = self._rules.get("TAX_WITHHOLDING_PPH23")
        if rule_pph23 and rule_pph23.is_active:
            applicable = rule_pph23.parameters.get("applicable_transactions", [])
            if transaction_type in applicable and supplier_type == "PKP" and not is_intercompany:
                # In production, would check if withholding was applied
                # For now, just log and optionally raise warning
                logger.info(f"Transaction {transaction_type} requires PPh 23 withholding")

        # Check PPh 26 for foreign parties
        rule_pph26 = self._rules.get("TAX_WITHHOLDING_PPH26")
        if rule_pph26 and rule_pph26.is_active and supplier_type == "FOREIGN":
            rate = Decimal(str(rule_pph26.parameters.get("rate", 0.20)))
            expected_withholding = amount * rate
            logger.info(f"Foreign transaction requires PPh 26 withholding: {expected_withholding}")

        # Check tax invoice requirement
        rule_invoice = self._rules.get("TAX_INVOICE_PPK")
        if rule_invoice and rule_invoice.is_active and supplier_type == "PKP":
            threshold = Decimal(
                str(await self._config.get_config("tax_invoice_threshold", 1000000))
            )
            if amount >= threshold:
                # Should have tax invoice
                logger.info(f"Transaction amount {amount} >= {threshold}, tax invoice required")

        return True, None

    async def check_transfer_pricing(
        self,
        amount: Decimal,
        fair_market_value: Decimal,
        related_party_id: UUID,
        legal_entity_id: UUID | None = None,
        transaction_id: UUID | None = None,
        user_id: str | None = None,
    ) -> tuple[bool, ComplianceViolation | None]:
        """
        Memeriksa kepatuhan transfer pricing antar perusahaan terafiliasi.

        Returns:
            (is_compliant, violation_if_deviation_exceeds_tolerance)
        """
        rule = self._rules.get("TRANSFER_PRICING_ARM_LENGTH")
        if not rule or not rule.is_active:
            return True, None

        tolerance_percent = Decimal(
            str(await self._config.get_config("transfer_pricing_tolerance_percent", 5))
        )
        if fair_market_value > 0:
            deviation = abs(amount - fair_market_value) / fair_market_value * 100
        else:
            deviation = Decimal(0)

        if deviation > tolerance_percent:
            violation = self._create_violation(
                rule_id=rule.rule_id,
                domain=rule.domain,
                severity=rule.severity,
                transaction_id=transaction_id,
                legal_entity_id=legal_entity_id,
                user_id=user_id,
                amount=amount,
                currency="IDR",
                message=f"Intercompany transaction deviates {deviation:.2f}% from fair market value. Transfer pricing documentation required.",
                details={
                    "amount": str(amount),
                    "fair_market_value": str(fair_market_value),
                    "deviation_percent": str(deviation),
                    "tolerance_percent": str(tolerance_percent),
                    "related_party_id": str(related_party_id),
                },
            )
            return False, violation

        return True, None

    async def check_fx_reporting(
        self,
        amount: Decimal,
        currency: str,
        legal_entity_id: UUID | None = None,
        transaction_id: UUID | None = None,
        user_id: str | None = None,
    ) -> tuple[bool, ComplianceViolation | None]:
        """
        Memeriksa kewajiban pelaporan transaksi valas ke BI.

        Returns:
            (is_compliant, violation_if_reporting_required_but_not_done)
        """
        rule = self._rules.get("FX_REPORTING")
        if not rule or not rule.is_active:
            return True, None

        if currency.upper() == "IDR":
            return True, None

        reporting_threshold = Decimal(
            str(await self._config.get_config("fx_reporting_threshold_usd", 100000))
        )
        if amount > reporting_threshold:
            # Violation is just a warning that reporting is required
            violation = self._create_violation(
                rule_id=rule.rule_id,
                domain=rule.domain,
                severity=rule.severity,
                transaction_id=transaction_id,
                legal_entity_id=legal_entity_id,
                user_id=user_id,
                amount=amount,
                currency=currency,
                message=f"Foreign exchange transaction {amount} {currency} exceeds reporting threshold. Must report to BI.",
                details={
                    "amount": str(amount),
                    "currency": currency,
                    "threshold": str(reporting_threshold),
                },
            )
            return False, violation

        return True, None

    async def check_corporate_action(
        self,
        action_type: str,
        amount: Decimal,
        legal_entity_id: UUID | None = None,
        transaction_id: UUID | None = None,
        user_id: str | None = None,
        has_board_approval: bool = False,
    ) -> tuple[bool, ComplianceViolation | None]:
        """
        Memeriksa kepatuhan corporate action (dividen, merger, dll).

        Returns:
            (is_compliant, violation_if_approval_missing)
        """
        rule = self._rules.get("CORPORATE_ACTION_APPROVAL")
        if not rule or not rule.is_active:
            return True, None

        if not has_board_approval:
            violation = self._create_violation(
                rule_id=rule.rule_id,
                domain=rule.domain,
                severity=rule.severity,
                transaction_id=transaction_id,
                legal_entity_id=legal_entity_id,
                user_id=user_id,
                amount=amount,
                currency="IDR",
                message=f"Corporate action {action_type} requires board approval. No approval found.",
                details={"action_type": action_type, "amount": str(amount)},
            )
            return False, violation

        return True, None

    async def enforce(
        self,
        checks: list[tuple[str, dict[str, Any]]],
        legal_entity_id: UUID | None = None,
        user_id: str | None = None,
        raise_on_violation: bool = True,
    ) -> tuple[bool, list[ComplianceViolation]]:
        """
        Menjalankan serangkaian pemeriksaan regulasi.

        Args:
            checks: List of (check_name, parameters)
            legal_entity_id: Entitas hukum
            user_id: User ID
            raise_on_violation: Raise exception jika violation dengan severity CRITICAL

        Returns:
            (is_compliant, list_of_violations)
        """
        if not self._enabled:
            return True, []

        if legal_entity_id is None:
            legal_entity_id = get_current_legal_entity()
        if user_id is None:
            user_id = get_current_user()

        violations = []

        for check_name, params in checks:
            if check_name == "foreign_exchange_limit":
                is_ok, violation = await self.check_foreign_exchange_limit(
                    amount=params.get("amount", Decimal(0)),
                    currency=params.get("currency", "IDR"),
                    legal_entity_id=legal_entity_id,
                    transaction_id=params.get("transaction_id"),
                    user_id=user_id,
                )
                if violation:
                    self._record_violation(violation)
                    violations.append(violation)

            elif check_name == "aml_threshold":
                is_ok, violation = await self.check_aml_threshold(
                    amount=params.get("amount", Decimal(0)),
                    customer_id=params.get("customer_id"),
                    legal_entity_id=legal_entity_id,
                    transaction_id=params.get("transaction_id"),
                    user_id=user_id,
                )
                if violation:
                    self._record_violation(violation)
                    violations.append(violation)
                    # Record for structuring detection
                    if params.get("customer_id"):
                        self._record_transaction(
                            params["customer_id"],
                            {
                                "amount": params.get("amount", 0),
                                "timestamp": params.get("transaction_date", datetime.now(UTC)),
                                "transaction_id": params.get("transaction_id"),
                            },
                        )

            elif check_name == "aml_structuring":
                if params.get("customer_id"):
                    is_ok, violation = await self.check_aml_structuring(
                        amount=params.get("amount", Decimal(0)),
                        customer_id=params["customer_id"],
                        transaction_date=params.get("transaction_date", datetime.now(UTC)),
                        legal_entity_id=legal_entity_id,
                        transaction_id=params.get("transaction_id"),
                        user_id=user_id,
                    )
                    if violation:
                        self._record_violation(violation)
                        violations.append(violation)

            elif check_name == "tax_withholding":
                is_ok, violation = await self.check_tax_withholding(
                    transaction_type=params.get("transaction_type", ""),
                    amount=params.get("amount", Decimal(0)),
                    supplier_type=params.get("supplier_type"),
                    is_intercompany=params.get("is_intercompany", False),
                    legal_entity_id=legal_entity_id,
                    transaction_id=params.get("transaction_id"),
                    user_id=user_id,
                )
                if violation:
                    self._record_violation(violation)
                    violations.append(violation)

            elif check_name == "transfer_pricing":
                is_ok, violation = await self.check_transfer_pricing(
                    amount=params.get("amount", Decimal(0)),
                    fair_market_value=params.get("fair_market_value", Decimal(0)),
                    related_party_id=params.get("related_party_id"),
                    legal_entity_id=legal_entity_id,
                    transaction_id=params.get("transaction_id"),
                    user_id=user_id,
                )
                if violation:
                    self._record_violation(violation)
                    violations.append(violation)

            elif check_name == "fx_reporting":
                is_ok, violation = await self.check_fx_reporting(
                    amount=params.get("amount", Decimal(0)),
                    currency=params.get("currency", "IDR"),
                    legal_entity_id=legal_entity_id,
                    transaction_id=params.get("transaction_id"),
                    user_id=user_id,
                )
                if violation:
                    self._record_violation(violation)
                    violations.append(violation)

            elif check_name == "corporate_action":
                is_ok, violation = await self.check_corporate_action(
                    action_type=params.get("action_type", ""),
                    amount=params.get("amount", Decimal(0)),
                    legal_entity_id=legal_entity_id,
                    transaction_id=params.get("transaction_id"),
                    user_id=user_id,
                    has_board_approval=params.get("has_board_approval", False),
                )
                if violation:
                    self._record_violation(violation)
                    violations.append(violation)

        # Raise if any CRITICAL violation
        if raise_on_violation:
            critical_violations = [
                v for v in violations if v.severity == ComplianceSeverity.CRITICAL
            ]
            if critical_violations:
                raise RegulatoryComplianceError(
                    message=f"Regulatory compliance violation(s): {', '.join(v.message for v in critical_violations[:3])}",
                    domain=critical_violations[0].domain.value,
                    rule_id=critical_violations[0].rule_id,
                    severity=GuardSeverity.CRITICAL,
                    details={"violations": [v.to_dict() for v in critical_violations]},
                )

        return len(violations) == 0, violations

    def _create_violation(
        self,
        rule_id: str,
        domain: RegulatoryDomain,
        severity: ComplianceSeverity,
        transaction_id: UUID | None,
        legal_entity_id: UUID | None,
        user_id: str | None,
        amount: Decimal | None,
        currency: str | None,
        message: str,
        details: dict[str, Any],
    ) -> ComplianceViolation:
        """Membuat record pelanggaran regulasi."""
        violation = ComplianceViolation(
            violation_id=uuid4(),
            rule_id=rule_id,
            domain=domain,
            severity=severity,
            transaction_id=transaction_id,
            legal_entity_id=legal_entity_id,
            user_id=user_id,
            amount=amount,
            currency=currency,
            message=message,
            details=details,
            detected_at=datetime.now(UTC),
            is_resolved=False,
            report_sent_to_regulator=False,
            cryptographic_hash="",
        )
        violation = ComplianceViolation(
            **{**violation.__dict__, "cryptographic_hash": violation.compute_hash()}
        )
        return violation

    def _record_violation(self, violation: ComplianceViolation) -> None:
        """Mencatat pelanggaran ke history."""
        with self._lock:
            self._violations.append(violation)
            if len(self._violations) > self._max_history:
                self._violations = self._violations[-self._max_history :]

            # If configured, send report to regulator (simulate)
            if self._report_violations_to_regulator and violation.severity in (
                ComplianceSeverity.CRITICAL,
                ComplianceSeverity.HIGH,
            ):
                # In production, would call external API
                logger.warning(
                    f"Would send report to regulator for violation {violation.violation_id}"
                )

    def _record_transaction(self, customer_id: UUID, transaction: dict[str, Any]) -> None:
        """Merekam transaksi untuk deteksi structuring."""
        with self._lock:
            if customer_id not in self._transaction_history:
                self._transaction_history[customer_id] = []
            self._transaction_history[customer_id].append(transaction)
            # Limit history per customer
            if len(self._transaction_history[customer_id]) > 100:
                self._transaction_history[customer_id] = self._transaction_history[customer_id][
                    -100:
                ]

    def _get_customer_transactions(
        self,
        customer_id: UUID,
        from_date: datetime,
        to_date: datetime,
    ) -> list[dict[str, Any]]:
        """Mendapatkan transaksi customer dalam rentang waktu."""
        with self._lock:
            transactions = self._transaction_history.get(customer_id, [])
        return [t for t in transactions if from_date <= t.get("timestamp", datetime.min) <= to_date]

    def get_violations(
        self,
        limit: int = 100,
        domain: RegulatoryDomain | None = None,
        unresolved_only: bool = False,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[ComplianceViolation]:
        """Mendapatkan history pelanggaran regulasi."""
        with self._lock:
            result = self._violations[-limit:]
        if domain:
            result = [v for v in result if v.domain == domain]
        if unresolved_only:
            result = [v for v in result if not v.is_resolved]
        if start_date:
            result = [v for v in result if v.detected_at >= start_date]
        if end_date:
            result = [v for v in result if v.detected_at <= end_date]
        return result

    def resolve_violation(
        self,
        violation_id: UUID,
        resolved_by: str,
        resolution_action: str,
    ) -> ComplianceViolation | None:
        """Menandai pelanggaran sebagai resolved."""
        with self._lock:
            for i, v in enumerate(self._violations):
                if v.violation_id == violation_id and not v.is_resolved:
                    resolved = v.resolve(resolved_by, resolution_action)
                    self._violations[i] = resolved
                    self._record_audit("RESOLVE_VIOLATION", resolved_by, {"violation_id": str(violation_id)})
                    logger.info(f"Compliance violation {violation_id} resolved by {resolved_by}")
                    return resolved
        return None

    def mark_violation_reported(
        self, violation_id: UUID, reported_by: str
    ) -> ComplianceViolation | None:
        """Menandai bahwa laporan pelanggaran telah dikirim ke regulator."""
        with self._lock:
            for i, v in enumerate(self._violations):
                if v.violation_id == violation_id and not v.report_sent_to_regulator:
                    reported = v.mark_report_sent(reported_by)
                    self._violations[i] = reported
                    self._record_audit("MARK_REPORTED", reported_by, {"violation_id": str(violation_id)})
                    logger.info(
                        f"Compliance violation {violation_id} marked as reported to regulator by {reported_by}"
                    )
                    return reported
        return None

    def get_statistics(self) -> dict[str, Any]:
        """Mendapatkan statistik kepatuhan regulasi."""
        with self._lock:
            total = len(self._violations)
            if total == 0:
                return {"total_violations": 0, "enabled": self._enabled, "version": self._version}

            by_domain: dict[str, int] = {}
            by_severity: dict[str, int] = {}
            unresolved = 0
            reported = 0

            for v in self._violations:
                by_domain[v.domain.value] = by_domain.get(v.domain.value, 0) + 1
                by_severity[v.severity.name] = by_severity.get(v.severity.name, 0) + 1
                if not v.is_resolved:
                    unresolved += 1
                if v.report_sent_to_regulator:
                    reported += 1

            return {
                "total_violations": total,
                "unresolved_violations": unresolved,
                "reported_to_regulator": reported,
                "by_domain": by_domain,
                "by_severity": by_severity,
                "active_rules": len([r for r in self._rules.values() if r.is_active]),
                "enabled": self._enabled,
                "version": self._version,
                "latest_violation": self._violations[-1].detected_at.isoformat()
                if self._violations
                else None,
            }

    def reset(self) -> None:
        """Reset guard (untuk testing)."""
        with self._lock:
            self._violations = []
            self._transaction_history = {}
            self._rules = {r.rule_id: r for r in DEFAULT_REGULATORY_RULES}
            self._enabled = True
            self._version += 1
            self._audit_trail = []


# === 5. SINGLETON ACCESSOR ===

_regulatory_compliance_guard_instance: RegulatoryComplianceGuard | None = None
_lock_instance = threading.Lock()


def get_regulatory_compliance_guard() -> RegulatoryComplianceGuard:
    """Mendapatkan instance singleton RegulatoryComplianceGuard."""
    global _regulatory_compliance_guard_instance
    if _regulatory_compliance_guard_instance is None:
        with _lock_instance:
            if _regulatory_compliance_guard_instance is None:
                _regulatory_compliance_guard_instance = RegulatoryComplianceGuard()
    return _regulatory_compliance_guard_instance


# === 6. EXPORTS ===

__all__ = [
    "ComplianceSeverity",
    "ComplianceViolation",
    "RegulatoryComplianceGuard",
    "RegulatoryDomain",
    "RegulatoryRule",
    "get_regulatory_compliance_guard",
]
