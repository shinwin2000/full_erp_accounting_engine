#!/usr/bin/env python3
"""
Module: reality_exceptions.py
Layer: 5 - Reality, Intent, Causality / Reality
Responsibility: Exception terkait pemetaan realitas ke akuntansi.
               Mendefinisikan hierarchy exception untuk semua error yang
               terjadi di layer reality, termasuk validasi event ekonomi,
               pemetaan ke jurnal, dan verifikasi aset.

Dependencies:
- standard library (enum, typing)

Audit: Setiap exception reality dictat.
"""

from __future__ import annotations

from enum import Enum, auto
from typing import Any

# === 1. CONSTANTS & ENUMS ===


class RealityErrorCode(Enum):
    """Kode error untuk reality layer."""

    # Economic event errors
    EVENT_NOT_FOUND = auto()
    EVENT_INVALID_STATUS = auto()
    EVENT_ALREADY_MAPPED = auto()
    EVENT_ALREADY_POSTED = auto()
    EVENT_CANNOT_REVERSE = auto()

    # Validation errors
    VALIDATION_FAILED = auto()
    AMOUNT_INVALID = auto()
    DATE_INVALID = auto()
    CURRENCY_MISMATCH = auto()
    MISSING_REQUIRED_FIELD = auto()

    # Mapping errors
    MAPPING_NOT_FOUND = auto()
    MAPPING_INCOMPLETE = auto()
    ACCOUNT_NOT_FOUND = auto()
    JOURNAL_CREATION_FAILED = auto()

    # Asset verification errors
    ASSET_NOT_FOUND = auto()
    ASSET_VERIFICATION_FAILED = auto()
    ASSET_DUPLICATE = auto()
    ASSET_NOT_VERIFIED = auto()

    # Financial obligation/entitlement errors
    OBLIGATION_NOT_FOUND = auto()
    ENTITLEMENT_NOT_FOUND = auto()
    PAYMENT_EXCEEDS_BALANCE = auto()
    COLLECTION_EXCEEDS_BALANCE = auto()


class RealitySeverity(Enum):
    """Severity untuk reality error."""

    CRITICAL = 80  # Error fatal, transaksi ditolak
    HIGH = 60  # Error serius, perlu intervensi
    MEDIUM = 40  # Error yang dapat direcovery
    LOW = 20  # Warning, tidak menghentikan operasi


# === 2. BASE EXCEPTION ===


class RealityError(Exception):
    """
    Base exception untuk semua error di reality layer.

    Business context: Exception yang terjadi di layer reality harus
    mewarisi kelas ini untuk konsistensi handling.
    """

    def __init__(
        self,
        message: str,
        error_code: RealityErrorCode,
        severity: RealitySeverity = RealitySeverity.MEDIUM,
        component: str | None = None,
        details: dict[str, Any] | None = None,
        cause: Exception | None = None,
    ):
        self.error_code = error_code
        self.severity = severity
        self.component = component
        self.details = details or {}
        self.cause = cause

        full_message = f"[{severity.name}][{error_code.name}] {message}"
        if component:
            full_message = f"[{component}] {full_message}"
        super().__init__(full_message)
        self._original_message = message

    @property
    def original_message(self) -> str:
        return self._original_message

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.__class__.__name__,
            "error_code": self.error_code.name,
            "severity": self.severity.name,
            "message": self._original_message,
            "component": self.component,
            "details": self.details,
            "cause": str(self.cause) if self.cause else None,
        }

    def is_critical(self) -> bool:
        return self.severity == RealitySeverity.CRITICAL


# === 3. CONCRETE EXCEPTIONS ===


class EconomicEventNotFoundError(RealityError):
    """Economic event tidak ditemukan."""

    def __init__(self, event_id: str, **kwargs):
        super().__init__(
            message=f"Economic event {event_id} not found",
            error_code=RealityErrorCode.EVENT_NOT_FOUND,
            severity=RealitySeverity.HIGH,
            component="economic_event",
            details={"event_id": event_id},
            **kwargs,
        )
        self.event_id = event_id


class EconomicEventInvalidStatusError(RealityError):
    """Status economic event tidak valid untuk operasi yang diminta."""

    def __init__(self, event_id: str, current_status: str, required_status: str, **kwargs):
        super().__init__(
            message=f"Economic event {event_id} has invalid status {current_status}. Required: {required_status}",
            error_code=RealityErrorCode.EVENT_INVALID_STATUS,
            severity=RealitySeverity.HIGH,
            component="economic_event",
            details={
                "event_id": event_id,
                "current_status": current_status,
                "required_status": required_status,
            },
            **kwargs,
        )
        self.event_id = event_id


class EventAlreadyMappedError(RealityError):
    """Event sudah dipetakan ke jurnal."""

    def __init__(self, event_id: str, journal_id: str, **kwargs):
        super().__init__(
            message=f"Economic event {event_id} already mapped to journal {journal_id}",
            error_code=RealityErrorCode.EVENT_ALREADY_MAPPED,
            severity=RealitySeverity.MEDIUM,
            component="economic_event",
            details={"event_id": event_id, "journal_id": journal_id},
            **kwargs,
        )
        self.event_id = event_id


class ValidationFailedError(RealityError):
    """Validasi event gagal."""

    def __init__(self, message: str, issues: list, **kwargs):
        super().__init__(
            message=message,
            error_code=RealityErrorCode.VALIDATION_FAILED,
            severity=RealitySeverity.HIGH,
            component="validation",
            details={
                "issues": [
                    {
                        "field": getattr(i, "field", "unknown"),
                        "message": getattr(i, "message", str(i)),
                    }
                    for i in issues
                ]
            },
            **kwargs,
        )
        self.issues = issues


class MappingNotFoundError(RealityError):
    """Mapping untuk event type tidak ditemukan."""

    def __init__(self, event_type: str, **kwargs):
        super().__init__(
            message=f"No accounting mapping found for event type {event_type}",
            error_code=RealityErrorCode.MAPPING_NOT_FOUND,
            severity=RealitySeverity.CRITICAL,
            component="mapper",
            details={"event_type": event_type},
            **kwargs,
        )
        self.event_type = event_type


class AccountNotFoundError(RealityError):
    """Akun tidak ditemukan di COA."""

    def __init__(self, account_code: str, **kwargs):
        super().__init__(
            message=f"Account {account_code} not found in Chart of Accounts",
            error_code=RealityErrorCode.ACCOUNT_NOT_FOUND,
            severity=RealitySeverity.CRITICAL,
            component="mapper",
            details={"account_code": account_code},
            **kwargs,
        )
        self.account_code = account_code


class AssetNotFoundError(RealityError):
    """Aset tidak ditemukan."""

    def __init__(self, asset_id: str, **kwargs):
        super().__init__(
            message=f"Asset {asset_id} not found",
            error_code=RealityErrorCode.ASSET_NOT_FOUND,
            severity=RealitySeverity.HIGH,
            component="asset_validator",
            details={"asset_id": asset_id},
            **kwargs,
        )
        self.asset_id = asset_id


class AssetVerificationFailedError(RealityError):
    """Verifikasi aset gagal."""

    def __init__(self, asset_id: str, reason: str, **kwargs):
        super().__init__(
            message=f"Asset verification failed for {asset_id}: {reason}",
            error_code=RealityErrorCode.ASSET_VERIFICATION_FAILED,
            severity=RealitySeverity.HIGH,
            component="asset_validator",
            details={"asset_id": asset_id, "reason": reason},
            **kwargs,
        )
        self.asset_id = asset_id


class AssetDuplicateError(RealityError):
    """Aset duplikat terdeteksi."""

    def __init__(self, asset_id: str, existing_asset_id: str, **kwargs):
        super().__init__(
            message=f"Asset {asset_id} appears to be duplicate of {existing_asset_id}",
            error_code=RealityErrorCode.ASSET_DUPLICATE,
            severity=RealitySeverity.HIGH,
            component="asset_validator",
            details={"asset_id": asset_id, "existing_asset_id": existing_asset_id},
            **kwargs,
        )
        self.asset_id = asset_id


class AssetNotVerifiedError(RealityError):
    """Aset belum diverifikasi."""

    def __init__(self, asset_id: str, **kwargs):
        super().__init__(
            message=f"Asset {asset_id} has not been verified. Please verify existence first.",
            error_code=RealityErrorCode.ASSET_NOT_VERIFIED,
            severity=RealitySeverity.CRITICAL,
            component="asset_validator",
            details={"asset_id": asset_id},
            **kwargs,
        )
        self.asset_id = asset_id


class PaymentExceedsBalanceError(RealityError):
    """Pembayaran melebihi saldo kewajiban."""

    def __init__(self, obligation_id: str, payment_amount: str, outstanding_amount: str, **kwargs):
        super().__init__(
            message=f"Payment {payment_amount} exceeds outstanding balance {outstanding_amount} for obligation {obligation_id}",
            error_code=RealityErrorCode.PAYMENT_EXCEEDS_BALANCE,
            severity=RealitySeverity.HIGH,
            component="obligation",
            details={
                "obligation_id": obligation_id,
                "payment_amount": payment_amount,
                "outstanding_amount": outstanding_amount,
            },
            **kwargs,
        )
        self.obligation_id = obligation_id


class CollectionExceedsBalanceError(RealityError):
    """Penagihan melebihi saldo piutang."""

    def __init__(
        self, entitlement_id: str, collection_amount: str, outstanding_amount: str, **kwargs
    ):
        super().__init__(
            message=f"Collection {collection_amount} exceeds outstanding balance {outstanding_amount} for entitlement {entitlement_id}",
            error_code=RealityErrorCode.COLLECTION_EXCEEDS_BALANCE,
            severity=RealitySeverity.HIGH,
            component="entitlement",
            details={
                "entitlement_id": entitlement_id,
                "collection_amount": collection_amount,
                "outstanding_amount": outstanding_amount,
            },
            **kwargs,
        )
        self.entitlement_id = entitlement_id


# === 4. EXCEPTION FACTORY ===


class RealityExceptionFactory:
    """
    Factory untuk membuat reality exceptions dengan konsistensi.
    """

    @staticmethod
    def event_not_found(event_id: str, **kwargs) -> EconomicEventNotFoundError:
        return EconomicEventNotFoundError(event_id=event_id, **kwargs)

    @staticmethod
    def invalid_status(
        event_id: str, current: str, required: str, **kwargs
    ) -> EconomicEventInvalidStatusError:
        return EconomicEventInvalidStatusError(
            event_id=event_id, current_status=current, required_status=required, **kwargs
        )

    @staticmethod
    def mapping_not_found(event_type: str, **kwargs) -> MappingNotFoundError:
        return MappingNotFoundError(event_type=event_type, **kwargs)

    @staticmethod
    def account_not_found(account_code: str, **kwargs) -> AccountNotFoundError:
        return AccountNotFoundError(account_code=account_code, **kwargs)

    @staticmethod
    def asset_not_found(asset_id: str, **kwargs) -> AssetNotFoundError:
        return AssetNotFoundError(asset_id=asset_id, **kwargs)

    @staticmethod
    def asset_verification_failed(
        asset_id: str, reason: str, **kwargs
    ) -> AssetVerificationFailedError:
        return AssetVerificationFailedError(asset_id=asset_id, reason=reason, **kwargs)

    @staticmethod
    def asset_not_verified(asset_id: str, **kwargs) -> AssetNotVerifiedError:
        return AssetNotVerifiedError(asset_id=asset_id, **kwargs)

    @staticmethod
    def payment_exceeds_balance(
        obligation_id: str, payment: str, outstanding: str, **kwargs
    ) -> PaymentExceedsBalanceError:
        return PaymentExceedsBalanceError(
            obligation_id=obligation_id,
            payment_amount=payment,
            outstanding_amount=outstanding,
            **kwargs,
        )

    @staticmethod
    def collection_exceeds_balance(
        entitlement_id: str, collection: str, outstanding: str, **kwargs
    ) -> CollectionExceedsBalanceError:
        return CollectionExceedsBalanceError(
            entitlement_id=entitlement_id,
            collection_amount=collection,
            outstanding_amount=outstanding,
            **kwargs,
        )


# === 5. EXPORTS ===

__all__ = [
    "AccountNotFoundError",
    "AssetDuplicateError",
    "AssetNotFoundError",
    "AssetNotVerifiedError",
    "AssetVerificationFailedError",
    "CollectionExceedsBalanceError",
    "EconomicEventInvalidStatusError",
    "EconomicEventNotFoundError",
    "EventAlreadyMappedError",
    "MappingNotFoundError",
    "PaymentExceedsBalanceError",
    "RealityError",
    "RealityErrorCode",
    "RealityExceptionFactory",
    "RealitySeverity",
    "ValidationFailedError",
]
