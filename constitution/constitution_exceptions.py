#!/usr/bin/env python3
"""
Module: constitution_exceptions.py
Layer: 1 - Foundation / Constitution
Responsibility: Mendefinisikan semua exception terkait pelanggaran konstitusi,
               termasuk hierarchy exception, atribut tambahan untuk audit,
               dan mekanisme serialisasi untuk logging.

Dependencies:
- standard library (uuid, datetime, enum, typing, json)

Audit: Setiap exception yang di-throw harus tercatat di audit log
       dengan severity yang sesuai.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from enum import Enum, auto
from typing import Any
from uuid import UUID, uuid4

# === 1. CONSTANTS & ENUMS ===


class ConstitutionExceptionSeverity(Enum):
    """Tingkat keparahan exception konstitusi."""

    CATASTROPHIC = 100  # Sistem harus freeze atau restart
    CRITICAL = 80  # Operasi dibatalkan, perlu investigasi segera
    HIGH = 60  # Operasi ditolak, perlu review
    MEDIUM = 40  # Operasi ditolak, dapat dicoba ulang
    LOW = 20  # Warning, operasi dapat dilanjutkan dengan catatan
    INFO = 0  # Informasi saja


class ConstitutionExceptionCategory(Enum):
    """Kategori exception konstitusi."""

    CONSTITUTION_VIOLATION = auto()  # Pelanggaran aturan konstitusi
    SOVEREIGNTY_VIOLATION = auto()  # Pelanggaran kedaulatan
    AMENDMENT_ERROR = auto()  # Error dalam amendemen
    VERSION_LOCK_ERROR = auto()  # Error version lock
    INVARIANT_VIOLATION = auto()  # Pelanggaran invariant
    FORBIDDEN_STATE = auto()  # State terlarang
    ENFORCEMENT_ERROR = auto()  # Error dalam enforcement
    VALIDATION_ERROR = auto()  # Error validasi umum
    INTEGRITY_ERROR = auto()  # Error integritas data
    AUTHORIZATION_ERROR = auto()  # Error otorisasi


# === 2. BASE EXCEPTION ===


class ConstitutionException(Exception):
    """
    Base exception untuk semua exception terkait konstitusi.

    Business context: Semua exception yang berasal dari lapisan konstitusi
    harus mewarisi kelas ini untuk memudahkan handling dan logging.

    Attributes:
        exception_id: UUID unik untuk setiap instance exception
        severity: Tingkat keparahan
        category: Kategori exception
        module: Modul asal exception
        user_id: ID pengguna yang terkait (jika ada)
        command_id: ID command yang terkait (jika ada)
        transaction_id: ID transaksi yang terkait (jika ada)
        legal_entity_id: ID entitas hukum yang terkait (jika ada)
        context: Konteks tambahan (dictionary)
        timestamp: Waktu terjadinya exception
    """

    def __init__(
        self,
        message: str,
        severity: ConstitutionExceptionSeverity = ConstitutionExceptionSeverity.MEDIUM,
        category: ConstitutionExceptionCategory = ConstitutionExceptionCategory.CONSTITUTION_VIOLATION,
        exception_id: UUID | None = None,
        module: str | None = None,
        user_id: str | None = None,
        command_id: UUID | None = None,
        transaction_id: UUID | None = None,
        legal_entity_id: UUID | None = None,
        context: dict[str, Any] | None = None,
    ):
        self.exception_id = exception_id or uuid4()
        self.severity = severity
        self.category = category
        self.module = module
        self.user_id = user_id
        self.command_id = command_id
        self.transaction_id = transaction_id
        self.legal_entity_id = legal_entity_id
        self.context = context or {}
        self.timestamp = datetime.now(UTC)

        full_message = (
            f"[{severity.name}][{category.name}] {message} "
            f"(ID: {self.exception_id}, Module: {module or 'unknown'})"
        )
        super().__init__(full_message)
        self._original_message = message

    def original_message(self) -> str:
        """Mendapatkan pesan asli tanpa prefix."""
        return self._original_message

    @property
    def message(self) -> str:
        """Get the original message without prefix."""
        return self._original_message

    def to_dict(self) -> dict[str, Any]:
        """Konversi exception ke dictionary untuk logging."""
        return {
            "exception_id": str(self.exception_id),
            "severity": self.severity.name,
            "severity_value": self.severity.value,
            "category": self.category.name,
            "message": self._original_message,
            "module": self.module,
            "user_id": self.user_id,
            "command_id": str(self.command_id) if self.command_id else None,
            "transaction_id": str(self.transaction_id) if self.transaction_id else None,
            "legal_entity_id": str(self.legal_entity_id) if self.legal_entity_id else None,
            "timestamp": self.timestamp.isoformat(),
            "context": self.context,
        }

    def to_json(self) -> str:
        """Konversi exception ke JSON string untuk logging."""
        return json.dumps(self.to_dict(), default=str)

    def is_catastrophic(self) -> bool:
        """Memeriksa apakah exception bersifat catastrophic."""
        return self.severity == ConstitutionExceptionSeverity.CATASTROPHIC

    def is_critical(self) -> bool:
        """Memeriksa apakah exception bersifat critical."""
        return self.severity.value >= ConstitutionExceptionSeverity.CRITICAL.value

    def get_audit_entry(self) -> dict[str, Any]:
        """Mendapatkan entry untuk audit log."""
        return {
            "audit_type": "CONSTITUTION_EXCEPTION",
            "exception_id": str(self.exception_id),
            "severity": self.severity.name,
            "category": self.category.name,
            "message": self.original_message[:500],
            "module": self.module,
            "user_id": self.user_id,
            "timestamp": self.timestamp.isoformat(),
        }


# === 3. CONCRETE EXCEPTIONS ===


class ConstitutionalViolationException(ConstitutionException):
    """
    Exception untuk pelanggaran aturan konstitusi.

    Digunakan ketika suatu operasi melanggar aturan yang didefinisikan
    dalam supreme_law atau constitutional_invariants.

    Additional attributes:
        principle: Nama prinsip konstitusi yang dilanggar
        rule_id: ID aturan yang dilanggar
    """

    def __init__(
        self,
        message: str,
        principle: str | None = None,
        rule_id: UUID | None = None,
        **kwargs,
    ):
        super().__init__(
            message=message,
            category=ConstitutionExceptionCategory.CONSTITUTION_VIOLATION,
            **kwargs,
        )
        self.principle = principle
        self.rule_id = rule_id

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        result["principle"] = self.principle
        result["rule_id"] = str(self.rule_id) if self.rule_id else None
        return result


class SovereigntyViolationException(ConstitutionException):
    """
    Exception untuk pelanggaran kedaulatan sistem.

    Digunakan ketika ada upaya akses atau modifikasi yang melanggar
    batasan kedaulatan yang didefinisikan dalam sovereignty_declaration.

    Additional attributes:
        domain: Domain kedaulatan yang dilanggar
        operation: Operasi yang dicoba
        source: Sumber operasi (API, CLI, etc.)
    """

    def __init__(
        self,
        message: str,
        domain: str | None = None,
        operation: str | None = None,
        source: str | None = None,
        **kwargs,
    ):
        super().__init__(
            message=message,
            category=ConstitutionExceptionCategory.SOVEREIGNTY_VIOLATION,
            severity=ConstitutionExceptionSeverity.HIGH,
            **kwargs,
        )
        self.domain = domain
        self.operation = operation
        self.source = source

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        result["domain"] = self.domain
        result["operation"] = self.operation
        result["source"] = self.source
        return result


class AmendmentException(ConstitutionException):
    """
    Exception untuk error dalam proses amendemen konstitusi.

    Digunakan ketika proposal amendemen gagal, voting tidak mencapai
    kuorum, atau eksekusi amendemen error.

    Additional attributes:
        proposal_id: ID proposal amendemen
        amendment_type: Jenis amendemen yang gagal
    """

    def __init__(
        self,
        message: str,
        proposal_id: UUID | None = None,
        amendment_type: str | None = None,
        **kwargs,
    ):
        super().__init__(
            message=message,
            category=ConstitutionExceptionCategory.AMENDMENT_ERROR,
            **kwargs,
        )
        self.proposal_id = proposal_id
        self.amendment_type = amendment_type

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        result["proposal_id"] = str(self.proposal_id) if self.proposal_id else None
        result["amendment_type"] = self.amendment_type
        return result


class VersionLockException(ConstitutionException):
    """
    Exception untuk error terkait version lock.

    Digunakan ketika ada upaya modifikasi konstitusi pada saat sistem
    dalam keadaan LOCKED atau FROZEN.

    Additional attributes:
        current_state: Status lock saat ini
        required_state: Status lock yang diperlukan
    """

    def __init__(
        self,
        message: str,
        current_state: str | None = None,
        required_state: str | None = None,
        **kwargs,
    ):
        super().__init__(
            message=message,
            category=ConstitutionExceptionCategory.VERSION_LOCK_ERROR,
            **kwargs,
        )
        self.current_state = current_state
        self.required_state = required_state

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        result["current_state"] = self.current_state
        result["required_state"] = self.required_state
        return result


class InvariantViolationException(ConstitutionException):
    """
    Exception untuk pelanggaran constitutional invariant.

    Digunakan ketika suatu operasi menyebabkan pelanggaran terhadap
    invariant fundamental seperti accounting equation atau double entry.

    Additional attributes:
        invariant_type: Tipe invariant yang dilanggar
        invariant_name: Nama invariant
        actual_value: Nilai aktual yang menyebabkan pelanggaran
        expected_value: Nilai yang diharapkan
    """

    def __init__(
        self,
        message: str,
        invariant_type: str | None = None,
        invariant_name: str | None = None,
        actual_value: Any | None = None,
        expected_value: Any | None = None,
        **kwargs,
    ):
        # Invariant violation cenderung memiliki severity lebih tinggi
        severity = kwargs.pop("severity", ConstitutionExceptionSeverity.CRITICAL)
        super().__init__(
            message=message,
            category=ConstitutionExceptionCategory.INVARIANT_VIOLATION,
            severity=severity,
            **kwargs,
        )
        self.invariant_type = invariant_type
        self.invariant_name = invariant_name
        self.actual_value = actual_value
        self.expected_value = expected_value

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        result["invariant_type"] = self.invariant_type
        result["invariant_name"] = self.invariant_name
        # Hindari serialisasi nilai yang terlalu besar
        result["actual_value"] = str(self.actual_value) if self.actual_value is not None else None
        result["expected_value"] = (
            str(self.expected_value) if self.expected_value is not None else None
        )
        return result


class ForbiddenStateException(ConstitutionException):
    """
    Exception untuk upaya memasuki state terlarang.

    Digunakan ketika suatu operasi akan menyebabkan sistem memasuki
    state yang didefinisikan sebagai forbidden.

    Additional attributes:
        state_category: Kategori state terlarang
        state_name: Nama state terlarang
        current_state: State sistem saat ini
        attempted_action: Aksi yang dicoba
    """

    def __init__(
        self,
        message: str,
        state_category: str | None = None,
        state_name: str | None = None,
        current_state: dict[str, Any] | None = None,
        attempted_action: dict[str, Any] | None = None,
        **kwargs,
    ):
        super().__init__(
            message=message,
            category=ConstitutionExceptionCategory.FORBIDDEN_STATE,
            **kwargs,
        )
        self.state_category = state_category
        self.state_name = state_name
        self.current_state = current_state
        self.attempted_action = attempted_action

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        result["state_category"] = self.state_category
        result["state_name"] = self.state_name
        # Batasi ukuran dictionary yang diserialisasi
        result["current_state"] = (
            self._truncate_dict(self.current_state) if self.current_state else None
        )
        result["attempted_action"] = (
            self._truncate_dict(self.attempted_action) if self.attempted_action else None
        )
        return result

    def _truncate_dict(self, d: dict[str, Any], max_length: int = 500) -> dict[str, Any]:
        """Memotong nilai dictionary yang terlalu panjang."""
        result = {}
        for k, v in d.items():
            if isinstance(v, str) and len(v) > max_length:
                result[k] = v[:max_length] + "..."
            elif isinstance(v, dict):
                result[k] = self._truncate_dict(v, max_length)
            else:
                result[k] = v
        return result


class EnforcementException(ConstitutionException):
    """
    Exception untuk error dalam enforcement pipeline.

    Digunakan ketika terjadi error internal saat menjalankan
    enforcement pipeline, bukan karena pelanggaran aturan.

    Additional attributes:
        stage: Tahapan enforcement yang gagal
        operation_id: ID operasi yang sedang di-enforce
    """

    def __init__(
        self,
        message: str,
        stage: str | None = None,
        operation_id: UUID | None = None,
        **kwargs,
    ):
        super().__init__(
            message=message,
            category=ConstitutionExceptionCategory.ENFORCEMENT_ERROR,
            **kwargs,
        )
        self.stage = stage
        self.operation_id = operation_id

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        result["stage"] = self.stage
        result["operation_id"] = str(self.operation_id) if self.operation_id else None
        return result


class IntegrityException(ConstitutionException):
    """
    Exception untuk error integritas data.

    Digunakan ketika terdeteksi kerusakan atau tampering pada data
    konstitusi, hash chain, atau audit trail.

    Additional attributes:
        expected_hash: Hash yang diharapkan
        actual_hash: Hash aktual yang ditemukan
        affected_entity: Entitas yang terkena dampak
    """

    def __init__(
        self,
        message: str,
        expected_hash: str | None = None,
        actual_hash: str | None = None,
        affected_entity: str | None = None,
        **kwargs,
    ):
        super().__init__(
            message=message,
            category=ConstitutionExceptionCategory.INTEGRITY_ERROR,
            severity=ConstitutionExceptionSeverity.CATASTROPHIC,
            **kwargs,
        )
        self.expected_hash = expected_hash
        self.actual_hash = actual_hash
        self.affected_entity = affected_entity

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        result["expected_hash"] = self.expected_hash[:16] + "..." if self.expected_hash else None
        result["actual_hash"] = self.actual_hash[:16] + "..." if self.actual_hash else None
        result["affected_entity"] = self.affected_entity
        return result


class AuthorizationException(ConstitutionException):
    """
    Exception untuk error otorisasi.

    Digunakan ketika pengguna tidak memiliki hak yang cukup untuk
    melakukan operasi yang memerlukan approval khusus.

    Additional attributes:
        required_roles: Peran yang diperlukan
        user_roles: Peran pengguna saat ini
        required_approvers: Approver yang diperlukan
    """

    def __init__(
        self,
        message: str,
        required_roles: list[str] | None = None,
        user_roles: list[str] | None = None,
        required_approvers: list[str] | None = None,
        **kwargs,
    ):
        super().__init__(
            message=message,
            category=ConstitutionExceptionCategory.AUTHORIZATION_ERROR,
            severity=ConstitutionExceptionSeverity.HIGH,
            **kwargs,
        )
        self.required_roles = required_roles
        self.user_roles = user_roles
        self.required_approvers = required_approvers

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        result["required_roles"] = self.required_roles
        result["user_roles"] = self.user_roles
        result["required_approvers"] = self.required_approvers
        return result


class ValidationException(ConstitutionException):
    """
    Exception untuk error validasi umum.

    Digunakan ketika data atau parameter tidak memenuhi syarat
    yang ditentukan oleh konstitusi.

    Additional attributes:
        field: Field yang gagal validasi
        invalid_value: Nilai yang tidak valid
        validation_rule: Aturan validasi yang dilanggar
    """

    def __init__(
        self,
        message: str,
        field: str | None = None,
        invalid_value: Any | None = None,
        validation_rule: str | None = None,
        **kwargs,
    ):
        super().__init__(
            message=message,
            category=ConstitutionExceptionCategory.VALIDATION_ERROR,
            severity=ConstitutionExceptionSeverity.MEDIUM,
            **kwargs,
        )
        self.field = field
        self.invalid_value = invalid_value
        self.validation_rule = validation_rule

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        result["field"] = self.field
        result["invalid_value"] = (
            str(self.invalid_value) if self.invalid_value is not None else None
        )
        result["validation_rule"] = self.validation_rule
        return result


# === 4. EXCEPTION FACTORY ===


class ConstitutionExceptionFactory:
    """
    Factory untuk membuat exception konstitusi dengan konsistensi.

    Business context: Memudahkan pembuatan exception dengan parameter
    default yang sesuai untuk kategori tertentu.

    Design pattern: Static factory methods.
    """

    @staticmethod
    def create_violation(
        message: str,
        principle: str | None = None,
        rule_id: UUID | None = None,
        severity: ConstitutionExceptionSeverity = ConstitutionExceptionSeverity.HIGH,
        **kwargs,
    ) -> ConstitutionalViolationException:
        """Membuat ConstitutionalViolationException."""
        return ConstitutionalViolationException(
            message=message,
            principle=principle,
            rule_id=rule_id,
            severity=severity,
            **kwargs,
        )

    @staticmethod
    def create_sovereignty_violation(
        message: str,
        domain: str | None = None,
        operation: str | None = None,
        source: str | None = None,
        **kwargs,
    ) -> SovereigntyViolationException:
        """Membuat SovereigntyViolationException."""
        return SovereigntyViolationException(
            message=message,
            domain=domain,
            operation=operation,
            source=source,
            **kwargs,
        )

    @staticmethod
    def create_amendment_error(
        message: str,
        proposal_id: UUID | None = None,
        amendment_type: str | None = None,
        **kwargs,
    ) -> AmendmentException:
        """Membuat AmendmentException."""
        return AmendmentException(
            message=message,
            proposal_id=proposal_id,
            amendment_type=amendment_type,
            **kwargs,
        )

    @staticmethod
    def create_version_lock_error(
        message: str,
        current_state: str | None = None,
        required_state: str | None = None,
        **kwargs,
    ) -> VersionLockException:
        """Membuat VersionLockException."""
        return VersionLockException(
            message=message,
            current_state=current_state,
            required_state=required_state,
            **kwargs,
        )

    @staticmethod
    def create_invariant_violation(
        message: str,
        invariant_type: str | None = None,
        invariant_name: str | None = None,
        actual_value: Any | None = None,
        expected_value: Any | None = None,
        **kwargs,
    ) -> InvariantViolationException:
        """Membuat InvariantViolationException."""
        return InvariantViolationException(
            message=message,
            invariant_type=invariant_type,
            invariant_name=invariant_name,
            actual_value=actual_value,
            expected_value=expected_value,
            **kwargs,
        )

    @staticmethod
    def create_forbidden_state(
        message: str,
        state_category: str | None = None,
        state_name: str | None = None,
        current_state: dict[str, Any] | None = None,
        attempted_action: dict[str, Any] | None = None,
        **kwargs,
    ) -> ForbiddenStateException:
        """Membuat ForbiddenStateException."""
        return ForbiddenStateException(
            message=message,
            state_category=state_category,
            state_name=state_name,
            current_state=current_state,
            attempted_action=attempted_action,
            **kwargs,
        )

    @staticmethod
    def create_enforcement_error(
        message: str,
        stage: str | None = None,
        operation_id: UUID | None = None,
        **kwargs,
    ) -> EnforcementException:
        """Membuat EnforcementException."""
        return EnforcementException(
            message=message,
            stage=stage,
            operation_id=operation_id,
            **kwargs,
        )

    @staticmethod
    def create_integrity_error(
        message: str,
        expected_hash: str | None = None,
        actual_hash: str | None = None,
        affected_entity: str | None = None,
        **kwargs,
    ) -> IntegrityException:
        """Membuat IntegrityException."""
        return IntegrityException(
            message=message,
            expected_hash=expected_hash,
            actual_hash=actual_hash,
            affected_entity=affected_entity,
            **kwargs,
        )

    @staticmethod
    def create_authorization_error(
        message: str,
        required_roles: list[str] | None = None,
        user_roles: list[str] | None = None,
        required_approvers: list[str] | None = None,
        **kwargs,
    ) -> AuthorizationException:
        """Membuat AuthorizationException."""
        return AuthorizationException(
            message=message,
            required_roles=required_roles,
            user_roles=user_roles,
            required_approvers=required_approvers,
            **kwargs,
        )

    @staticmethod
    def create_validation_error(
        message: str,
        field: str | None = None,
        invalid_value: Any | None = None,
        validation_rule: str | None = None,
        **kwargs,
    ) -> ValidationException:
        """Membuat ValidationException."""
        return ValidationException(
            message=message,
            field=field,
            invalid_value=invalid_value,
            validation_rule=validation_rule,
            **kwargs,
        )

    @staticmethod
    def from_violation_record(violation_record: Any) -> ConstitutionException:
        """
        Membuat exception dari violation record.

        Args:
            violation_record: Record pelanggaran dari supreme_law atau invariants

        Returns:
            ConstitutionException yang sesuai
        """
        # Hindari circular import dengan import lokal
        from constitution.constitutional_invariants import InvariantViolation
        from constitution.supreme_law import ViolationRecord as SupremeViolationRecord

        if isinstance(violation_record, SupremeViolationRecord):
            severity_map = {
                100: ConstitutionExceptionSeverity.CATASTROPHIC,
                70: ConstitutionExceptionSeverity.CRITICAL,
                40: ConstitutionExceptionSeverity.HIGH,
                10: ConstitutionExceptionSeverity.MEDIUM,
                0: ConstitutionExceptionSeverity.LOW,
            }
            severity = severity_map.get(
                violation_record.severity.value, ConstitutionExceptionSeverity.MEDIUM
            )

            return ConstitutionalViolationException(
                message=violation_record.message,
                principle=violation_record.principle.name
                if hasattr(violation_record.principle, "name")
                else str(violation_record.principle),
                rule_id=violation_record.rule_id
                if violation_record.rule_id != UUID(int=0)
                else None,
                severity=severity,
                module=violation_record.offending_module,
                user_id=violation_record.offending_user,
                command_id=violation_record.offending_command_id,
                exception_id=violation_record.violation_id,
            )
        elif isinstance(violation_record, InvariantViolation):
            severity_map = {
                100: ConstitutionExceptionSeverity.CATASTROPHIC,
                80: ConstitutionExceptionSeverity.CRITICAL,
                60: ConstitutionExceptionSeverity.HIGH,
                40: ConstitutionExceptionSeverity.MEDIUM,
                20: ConstitutionExceptionSeverity.LOW,
            }
            severity = severity_map.get(
                violation_record.severity.value, ConstitutionExceptionSeverity.MEDIUM
            )

            return InvariantViolationException(
                message=violation_record.message,
                invariant_type=violation_record.invariant_type.name
                if hasattr(violation_record.invariant_type, "name")
                else str(violation_record.invariant_type),
                actual_value=violation_record.actual_value,
                expected_value=violation_record.expected_value,
                severity=severity,
                module=violation_record.offending_module,
                user_id=violation_record.offending_user,
                transaction_id=violation_record.transaction_id,
                legal_entity_id=violation_record.legal_entity_id,
            )
        else:
            return ConstitutionException(
                message=str(violation_record),
                severity=ConstitutionExceptionSeverity.MEDIUM,
            )


# === 5. EXCEPTION HANDLER UTILITY ===


class ConstitutionExceptionHandler:
    """
    Utility untuk menangani exception konstitusi secara terpusat.

    Business context: Menyediakan metode untuk logging, alerting,
    dan menentukan tindakan yang tepat berdasarkan severity exception.
    """

    @staticmethod
    def handle(exception: ConstitutionException) -> dict[str, Any]:
        """
        Menangani exception konstitusi: log, alert, dan tentukan tindakan.

        Returns:
            Dictionary dengan hasil handling
        """
        audit_entry = exception.get_audit_entry()

        # Log berdasarkan severity
        if exception.severity == ConstitutionExceptionSeverity.CATASTROPHIC:
            logger.critical(f"CATASTROPHIC: {exception}", extra={"audit": audit_entry})
            action = "SYSTEM_FREEZE_REQUIRED"
        elif exception.severity == ConstitutionExceptionSeverity.CRITICAL:
            logger.error(f"CRITICAL: {exception}", extra={"audit": audit_entry})
            action = "OPERATION_REJECTED_INVESTIGATE"
        elif exception.severity == ConstitutionExceptionSeverity.HIGH:
            logger.error(f"HIGH: {exception}", extra={"audit": audit_entry})
            action = "OPERATION_REJECTED_REVIEW"
        elif exception.severity == ConstitutionExceptionSeverity.MEDIUM:
            logger.warning(f"MEDIUM: {exception}", extra={"audit": audit_entry})
            action = "OPERATION_REJECTED_RETRY"
        elif exception.severity == ConstitutionExceptionSeverity.LOW:
            logger.warning(f"LOW: {exception}", extra={"audit": audit_entry})
            action = "WARNING_ONLY"
        else:
            logger.info(f"INFO: {exception}", extra={"audit": audit_entry})
            action = "LOG_ONLY"

        return {
            "handled": True,
            "exception_id": str(exception.exception_id),
            "severity": exception.severity.name,
            "category": exception.category.name,
            "action": action,
            "audit_entry": audit_entry,
        }

    @staticmethod
    def should_retry(exception: ConstitutionException) -> bool:
        """Memeriksa apakah operasi dapat dicoba ulang."""
        return exception.severity in [
            ConstitutionExceptionSeverity.MEDIUM,
            ConstitutionExceptionSeverity.LOW,
            ConstitutionExceptionSeverity.INFO,
        ]

    @staticmethod
    def requires_audit(exception: ConstitutionException) -> bool:
        """Memeriksa apakah exception memerlukan audit khusus."""
        return exception.severity.value >= ConstitutionExceptionSeverity.HIGH.value


# Setup logger
logger = logging.getLogger(__name__)


# === 6. ALIASES ===
EnforcementError = EnforcementException
InvariantViolationError = InvariantViolationException


# === 7. EXPORTS ===

__all__ = [
    # Enums
    "ConstitutionExceptionSeverity",
    "ConstitutionExceptionCategory",
    # Base exception
    "ConstitutionException",
    # Concrete exceptions
    "ConstitutionalViolationException",
    "SovereigntyViolationException",
    "AmendmentException",
    "VersionLockException",
    "InvariantViolationException",
    "ForbiddenStateException",
    "EnforcementException",
    "IntegrityException",
    "AuthorizationException",
    "ValidationException",
    # Factory
    "ConstitutionExceptionFactory",
    # Handler
    "ConstitutionExceptionHandler",
    # Aliases
    "EnforcementError",
    "InvariantViolationError",
]