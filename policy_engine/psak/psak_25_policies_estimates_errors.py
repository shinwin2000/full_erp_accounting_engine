#!/usr/bin/env python3
"""
Module: psak_25_policies_estimates_errors.py
Layer: 7 - Policy Engine & Standards / PSAK

Responsibility:
    PSAK 25: Kebijakan Akuntansi, Perubahan Estimasi Akuntansi, dan Kesalahan
    (setara dengan IAS 8).
    Mengatur pemilihan dan penerapan kebijakan akuntansi, perubahan estimasi
    akuntansi, dan koreksi kesalahan periode lalu. Menentukan perlakuan
    retrospektif (restatement) atau prospektif, serta pengungkapan yang diperlukan.

Dependencies:
    - datetime, decimal, enum, typing, dataclasses, uuid, hashlib, logging

Audit:
    Setiap perubahan kebijakan, estimasi, dan koreksi kesalahan dicatat dengan hash.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from enum import Enum
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================
class PSAK25ChangeType(Enum):
    CHANGE_IN_ACCOUNTING_POLICY = "perubahan_kebijakan_akuntansi"
    CHANGE_IN_ACCOUNTING_ESTIMATE = "perubahan_estimasi_akuntansi"
    CORRECTION_OF_PRIOR_PERIOD_ERROR = "koreksi_kesalahan_periode_lalu"


class PSAK25ApplicationMethod(Enum):
    RETROSPECTIVE_RESTATEMENT = "retrospektif_restatement"
    PROSPECTIVE_APPLICATION = "prospektif"
    CURRENT_PERIOD_ADJUSTMENT = "penyesuaian_periode_berjalan"


class PSAK25ErrorType(Enum):
    MATHEMATICAL_MISTAKE = "kesalahan_matematis"
    MISAPPLICATION_OF_POLICY = "penerapan_kebijakan_salah"
    OVERSIGHT_OR_MISINTERPRETATION = "kelalaian_atau_salah_interpretasi"
    FRAUD = "kecurangan"


class PSAK25ComplianceLevel(Enum):
    FULL = "penuh"
    SUBSTANTIAL = "substansial"
    PARTIAL = "sebagian"
    NON_COMPLIANT = "tidak_patuh"


# ============================================================================
# Exceptions
# ============================================================================
class PSAK25Error(Exception):
    pass


class ImpracticableError(PSAK25Error):
    pass


# ============================================================================
# Data Classes
# ============================================================================
@dataclass
class PSAK25AccountingPolicy:
    """Kebijakan akuntansi."""

    policy_id: UUID
    policy_name: str
    effective_date: datetime
    description: str
    is_mandatory_by_standard: bool = False
    previous_policy_id: UUID | None = None
    replaced_by_policy_id: UUID | None = None
    is_active: bool = True

    def to_dict(self) -> dict:
        return {
            "policy_id": str(self.policy_id),
            "policy_name": self.policy_name,
            "effective_date": self.effective_date.isoformat(),
            "description": self.description,
            "is_mandatory": self.is_mandatory_by_standard,
            "is_active": self.is_active,
        }


@dataclass
class PSAK25ChangeDetail:
    """Detail perubahan kebijakan/estimasi atau koreksi error."""

    change_id: UUID
    entity_id: UUID
    entity_name: str
    change_type: PSAK25ChangeType
    change_date: datetime
    description: str
    justification: str
    effected_accounts: list[str] = field(default_factory=list)
    previous_amount: Decimal = Decimal(0)
    corrected_amount: Decimal = Decimal(0)
    impact_on_retained_earnings: Decimal = Decimal(0)
    application_method: PSAK25ApplicationMethod = PSAK25ApplicationMethod.RETROSPECTIVE_RESTATEMENT
    is_impracticable: bool = False
    impracticable_reason: str = ""
    approved_by: UUID | None = None
    approved_date: datetime | None = None
    notes: str = ""
    is_mandatory: bool = False  # FIX: tambahkan field untuk menandai perubahan wajib

    def net_impact(self) -> Decimal:
        return self.corrected_amount - self.previous_amount

    def to_dict(self) -> dict:
        return {
            "change_id": str(self.change_id),
            "entity_id": str(self.entity_id),
            "entity_name": self.entity_name,
            "change_type": self.change_type.value,
            "change_date": self.change_date.isoformat(),
            "description": self.description,
            "justification": self.justification,
            "effected_accounts": self.effected_accounts,
            "previous_amount": str(self.previous_amount),
            "corrected_amount": str(self.corrected_amount),
            "net_impact": str(self.net_impact()),
            "impact_on_retained_earnings": str(self.impact_on_retained_earnings),
            "application_method": self.application_method.value,
            "is_impracticable": self.is_impracticable,
            "impracticable_reason": self.impracticable_reason,
            "approved_by": str(self.approved_by) if self.approved_by else None,
            "approved_date": self.approved_date.isoformat() if self.approved_date else None,
            "notes": self.notes,
            "is_mandatory": self.is_mandatory,
        }


@dataclass
class PSAK25ChangeRegister:
    """Register perubahan kebijakan, estimasi, dan koreksi error."""

    register_id: UUID
    entity_id: UUID
    entity_name: str
    reporting_period_end: datetime
    changes: list[PSAK25ChangeDetail] = field(default_factory=list)

    def total_impact_on_retained_earnings(self) -> Decimal:
        # FIX: tambahkan Decimal(0) sebagai nilai awal sum
        return sum((c.impact_on_retained_earnings for c in self.changes), Decimal(0))

    def changes_by_type(self, change_type: PSAK25ChangeType) -> list[PSAK25ChangeDetail]:
        return [c for c in self.changes if c.change_type == change_type]

    def to_dict(self) -> dict:
        return {
            "register_id": str(self.register_id),
            "entity_id": str(self.entity_id),
            "entity_name": self.entity_name,
            "reporting_period_end": self.reporting_period_end.isoformat(),
            "total_impact_retained_earnings": str(self.total_impact_on_retained_earnings()),
            "changes": [c.to_dict() for c in self.changes],
        }


@dataclass
class PSAK25ValidationResult:
    is_compliant: bool
    compliance_level: PSAK25ComplianceLevel
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    hash_sha256: str = ""

    def __post_init__(self):
        self.hash_sha256 = self._compute_hash()

    def _compute_hash(self) -> str:
        data = {
            "is_compliant": self.is_compliant,
            "level": self.compliance_level.value,
            "errors": self.errors,
            "warnings": self.warnings,
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    def add_error(self, error: str) -> None:
        self.errors.append(error)
        self.is_compliant = False
        if self.compliance_level != PSAK25ComplianceLevel.NON_COMPLIANT:
            self.compliance_level = PSAK25ComplianceLevel.NON_COMPLIANT

    def add_warning(self, warning: str) -> None:
        self.warnings.append(warning)
        if self.compliance_level == PSAK25ComplianceLevel.FULL:
            self.compliance_level = PSAK25ComplianceLevel.SUBSTANTIAL

    def to_dict(self) -> dict:
        return {
            "is_compliant": self.is_compliant,
            "compliance_level": self.compliance_level.value,
            "errors": self.errors,
            "warnings": self.warnings,
            "hash": self.hash_sha256,
        }


# ============================================================================
# Domain Services
# ============================================================================
class PSAK25ChangeService:
    """Service untuk perubahan kebijakan, estimasi, dan koreksi error."""

    @staticmethod
    def determine_application_method(
        change_type: PSAK25ChangeType,
        is_mandatory_change: bool,
        is_impracticable: bool,
        has_retrospective_effect: bool,
    ) -> PSAK25ApplicationMethod:
        """Menentukan metode penerapan sesuai PSAK 25."""
        if change_type == PSAK25ChangeType.CHANGE_IN_ACCOUNTING_POLICY:
            if is_mandatory_change:
                if is_impracticable:
                    return PSAK25ApplicationMethod.PROSPECTIVE_APPLICATION
                return PSAK25ApplicationMethod.RETROSPECTIVE_RESTATEMENT
            else:
                # Voluntary change harus retrospektif kecuali impracticable
                if is_impracticable:
                    return PSAK25ApplicationMethod.PROSPECTIVE_APPLICATION
                return PSAK25ApplicationMethod.RETROSPECTIVE_RESTATEMENT
        elif change_type == PSAK25ChangeType.CHANGE_IN_ACCOUNTING_ESTIMATE:
            return PSAK25ApplicationMethod.PROSPECTIVE_APPLICATION
        elif change_type == PSAK25ChangeType.CORRECTION_OF_PRIOR_PERIOD_ERROR:
            if is_impracticable:
                return PSAK25ApplicationMethod.PROSPECTIVE_APPLICATION
            return PSAK25ApplicationMethod.RETROSPECTIVE_RESTATEMENT
        return PSAK25ApplicationMethod.CURRENT_PERIOD_ADJUSTMENT

    @staticmethod
    def calculate_retrospective_adjustment(
        previous_amount: Decimal,
        corrected_amount: Decimal,
        tax_rate: Decimal = Decimal("0.22"),
    ) -> Decimal:
        """Menghitung penyesuaian retrospektif (net of tax)."""
        difference = corrected_amount - previous_amount
        tax_effect = difference * tax_rate
        return (difference - tax_effect).quantize(Decimal("0"), rounding=ROUND_HALF_EVEN)

    @staticmethod
    def is_impracticable_to_determine_effect(
        change_type: PSAK25ChangeType,
        reason: str,
    ) -> bool:
        """Memeriksa apakah impracticable (tidak praktis) untuk menentukan efek kumulatif."""
        # PSAK 25 mendefinisikan impracticable jika tidak dapat ditentukan setelah upaya wajar
        return len(reason) > 0


# ============================================================================
# Rules
# ============================================================================
class PSAK25Rules:
    """Aturan PSAK 25."""

    @staticmethod
    def validate_change(change: PSAK25ChangeDetail) -> PSAK25ValidationResult:
        result = PSAK25ValidationResult(
            is_compliant=True, compliance_level=PSAK25ComplianceLevel.FULL
        )
        if (
            change.change_type == PSAK25ChangeType.CHANGE_IN_ACCOUNTING_POLICY
            and not change.justification
            and not change.is_mandatory  # FIX: sekarang ada field is_mandatory
        ):
            result.add_error(
                "Perubahan kebijakan akuntansi sukarela harus memiliki justifikasi"
            )
        if (
            change.change_type == PSAK25ChangeType.CHANGE_IN_ACCOUNTING_ESTIMATE
            and change.application_method != PSAK25ApplicationMethod.PROSPECTIVE_APPLICATION
        ):
            result.add_error("Perubahan estimasi harus diterapkan secara prospektif")
        if (
            change.change_type == PSAK25ChangeType.CORRECTION_OF_PRIOR_PERIOD_ERROR
            and change.is_impracticable
            and not change.impracticable_reason
        ):
            result.add_error("Ketidakpraktisan harus dijelaskan")
        return result

    @staticmethod
    def validate_disclosure(register: PSAK25ChangeRegister) -> PSAK25ValidationResult:
        result = PSAK25ValidationResult(
            is_compliant=True, compliance_level=PSAK25ComplianceLevel.FULL
        )
        for change in register.changes:
            if (
                change.change_type == PSAK25ChangeType.CHANGE_IN_ACCOUNTING_POLICY
                and not change.justification
            ):
                result.add_warning("Pengungkapan alasan perubahan kebijakan tidak lengkap")
            if (
                change.change_type == PSAK25ChangeType.CORRECTION_OF_PRIOR_PERIOD_ERROR
                and not change.effected_accounts
            ):
                result.add_warning(
                    "Akun-akun yang terpengaruh oleh koreksi kesalahan tidak diungkapkan"
                )
        return result


# ============================================================================
# Validator
# ============================================================================
class PSAK25Validator:
    def __init__(self):
        self._rules = PSAK25Rules()
        self._service = PSAK25ChangeService()

    def create_change(
        self,
        entity_id: UUID,
        entity_name: str,
        change_type: PSAK25ChangeType,
        description: str,
        justification: str,
        previous_amount: Decimal = Decimal(0),
        corrected_amount: Decimal = Decimal(0),
        effected_accounts: list[str] | None = None,
        is_mandatory_change: bool = False,
        is_impracticable: bool = False,
        impracticable_reason: str = "",
    ) -> PSAK25ChangeDetail:
        application_method = self._service.determine_application_method(
            change_type=change_type,
            is_mandatory_change=is_mandatory_change,
            is_impracticable=is_impracticable,
            has_retrospective_effect=True,
        )
        impact = Decimal(0)
        if (
            change_type in (
                PSAK25ChangeType.CHANGE_IN_ACCOUNTING_POLICY,
                PSAK25ChangeType.CORRECTION_OF_PRIOR_PERIOD_ERROR,
            )
            and application_method == PSAK25ApplicationMethod.RETROSPECTIVE_RESTATEMENT
        ):
            impact = self._service.calculate_retrospective_adjustment(
                previous_amount, corrected_amount
            )
        return PSAK25ChangeDetail(
            change_id=uuid4(),
            entity_id=entity_id,
            entity_name=entity_name,
            change_type=change_type,
            change_date=datetime.now(UTC),
            description=description,
            justification=justification,
            effected_accounts=effected_accounts or [],
            previous_amount=previous_amount,
            corrected_amount=corrected_amount,
            impact_on_retained_earnings=impact,
            application_method=application_method,
            is_impracticable=is_impracticable,
            impracticable_reason=impracticable_reason,
            is_mandatory=is_mandatory_change,  # FIX: simpan status mandatory
        )

    def create_register(
        self,
        entity_id: UUID,
        entity_name: str,
        reporting_period_end: datetime,
    ) -> PSAK25ChangeRegister:
        return PSAK25ChangeRegister(
            register_id=uuid4(),
            entity_id=entity_id,
            entity_name=entity_name,
            reporting_period_end=reporting_period_end,
        )

    def add_change(
        self, register: PSAK25ChangeRegister, change: PSAK25ChangeDetail
    ) -> PSAK25ChangeRegister:
        new_changes = [*register.changes, change]
        return PSAK25ChangeRegister(
            register_id=register.register_id,
            entity_id=register.entity_id,
            entity_name=register.entity_name,
            reporting_period_end=register.reporting_period_end,
            changes=new_changes,
        )

    def approve_change(self, change: PSAK25ChangeDetail, approver_id: UUID) -> PSAK25ChangeDetail:
        return PSAK25ChangeDetail(
            change_id=change.change_id,
            entity_id=change.entity_id,
            entity_name=change.entity_name,
            change_type=change.change_type,
            change_date=change.change_date,
            description=change.description,
            justification=change.justification,
            effected_accounts=change.effected_accounts,
            previous_amount=change.previous_amount,
            corrected_amount=change.corrected_amount,
            impact_on_retained_earnings=change.impact_on_retained_earnings,
            application_method=change.application_method,
            is_impracticable=change.is_impracticable,
            impracticable_reason=change.impracticable_reason,
            approved_by=approver_id,
            approved_date=datetime.now(UTC),
            notes=change.notes,
            is_mandatory=change.is_mandatory,
        )

    def validate_register(self, register: PSAK25ChangeRegister) -> PSAK25ValidationResult:
        result = PSAK25ValidationResult(
            is_compliant=True, compliance_level=PSAK25ComplianceLevel.FULL
        )
        for change in register.changes:
            result = self._merge_results(result, self._rules.validate_change(change))
        result = self._merge_results(result, self._rules.validate_disclosure(register))
        return result

    def _merge_results(
        self, main: PSAK25ValidationResult, other: PSAK25ValidationResult
    ) -> PSAK25ValidationResult:
        main.errors.extend(other.errors)
        main.warnings.extend(other.warnings)
        main.is_compliant = main.is_compliant and other.is_compliant
        level_order = [
            PSAK25ComplianceLevel.FULL,
            PSAK25ComplianceLevel.SUBSTANTIAL,
            PSAK25ComplianceLevel.PARTIAL,
            PSAK25ComplianceLevel.NON_COMPLIANT,
        ]
        main_idx = level_order.index(main.compliance_level)
        other_idx = level_order.index(other.compliance_level)
        if other_idx > main_idx:
            main.compliance_level = level_order[other_idx]
        return main

    def get_requirements_summary(self) -> dict:
        return {
            "accounting_policies": "Pilih dan terapkan kebijakan secara konsisten; perubahan hanya jika diwajibkan standar atau menghasilkan penyajian lebih relevan",
            "change_in_policy": "Diterapkan secara retrospektif (restatement) kecuali impracticable",
            "change_in_estimate": "Diterapkan secara prospektif (tidak restatement)",
            "correction_of_errors": "Diterapkan secara retrospektif pada periode pertama disajikan",
            "disclosures": [
                "Sifat perubahan kebijakan",
                "Alasan perubahan",
                "Jumlah penyesuaian untuk periode berjalan dan periode sebelumnya",
                "Untuk perubahan estimasi: efek pada periode berjalan dan periode mendatang",
                "Untuk koreksi error: sifat error dan jumlah koreksi",
            ],
        }


# ============================================================================
# Singleton Accessor
# ============================================================================
_psak25_validator_instance: PSAK25Validator | None = None


def get_psak25_validator() -> PSAK25Validator:
    global _psak25_validator_instance
    if _psak25_validator_instance is None:
        _psak25_validator_instance = PSAK25Validator()
    return _psak25_validator_instance


# ============================================================================
# Aliases for backward compatibility (FIX: resolves import errors)
# ============================================================================
# Alias untuk class utama
AccountingChangeLog = PSAK25ChangeRegister

# Alias untuk tipe perubahan (enum values) yang umum diimpor
ChangeInAccountingPolicy = PSAK25ChangeType.CHANGE_IN_ACCOUNTING_POLICY
ChangeInAccountingEstimate = PSAK25ChangeType.CHANGE_IN_ACCOUNTING_ESTIMATE
CorrectionOfPriorPeriodError = PSAK25ChangeType.CORRECTION_OF_PRIOR_PERIOD_ERROR

# Ekspos semua nama yang mungkin dibutuhkan
__all__ = [
    "AccountingChangeLog",
    "ChangeInAccountingEstimate",
    "ChangeInAccountingPolicy",
    "CorrectionOfPriorPeriodError",
    "PSAK25AccountingPolicy",
    "PSAK25ApplicationMethod",
    "PSAK25ChangeDetail",
    "PSAK25ChangeRegister",
    "PSAK25ChangeService",
    "PSAK25ChangeType",
    "PSAK25ComplianceLevel",
    "PSAK25ErrorType",
    "PSAK25Rules",
    "PSAK25ValidationResult",
    "PSAK25Validator",
    "get_psak25_validator",
]

# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    import json

    validator = get_psak25_validator()
    entity_id = uuid4()

    register = validator.create_register(
        entity_id=entity_id,
        entity_name="PT Akuntansi Profesional",
        reporting_period_end=datetime(2026, 12, 31, tzinfo=UTC),
    )

    # Example 1: Voluntary change in accounting policy (FIFO to Weighted Average)
    policy_change = validator.create_change(
        entity_id=entity_id,
        entity_name="PT Akuntansi Profesional",
        change_type=PSAK25ChangeType.CHANGE_IN_ACCOUNTING_POLICY,
        description="Perubahan metode penilaian persediaan dari FIFO ke rata-rata tertimbang",
        justification="Metode rata-rata tertimbang memberikan penyajian yang lebih relevan",
        previous_amount=Decimal("500000000"),
        corrected_amount=Decimal("520000000"),
        effected_accounts=["Persediaan", "HPP", "Laba Ditahan"],
        is_mandatory_change=False,
    )
    policy_change = validator.approve_change(policy_change, uuid4())
    register = validator.add_change(register, policy_change)

    # Example 2: Change in accounting estimate (useful life of asset)
    estimate_change = validator.create_change(
        entity_id=entity_id,
        entity_name="PT Akuntansi Profesional",
        change_type=PSAK25ChangeType.CHANGE_IN_ACCOUNTING_ESTIMATE,
        description="Revisi masa manfaat aset tetap dari 10 tahun menjadi 8 tahun",
        justification="Berdasarkan evaluasi teknis terbaru",
        previous_amount=Decimal("100000000"),
        corrected_amount=Decimal("125000000"),
        effected_accounts=["Beban Penyusutan", "Akumulasi Penyusutan"],
    )
    register = validator.add_change(register, estimate_change)

    # Example 3: Correction of prior period error (misstatement of revenue)
    error_correction = validator.create_change(
        entity_id=entity_id,
        entity_name="PT Akuntansi Profesional",
        change_type=PSAK25ChangeType.CORRECTION_OF_PRIOR_PERIOD_ERROR,
        description="Koreksi kesalahan pencatatan pendapatan tahun 2025",
        justification="Pendapatan dicatat terlalu tinggi",
        previous_amount=Decimal("100000000"),
        corrected_amount=Decimal("85000000"),
        effected_accounts=["Pendapatan", "Piutang Usaha", "Laba Ditahan"],
    )
    error_correction = validator.approve_change(error_correction, uuid4())
    register = validator.add_change(register, error_correction)

    # Validate
    result = validator.validate_register(register)
    print("Validation Result:")
    print(json.dumps(result.to_dict(), indent=2))
    print("\nChange Register:")
    print(json.dumps(register.to_dict(), indent=2, default=str))


# ============================================================================
# Additional compatibility stubs for __init__.py aggregator
# ============================================================================
class MaterialityLevel(Enum):
    MATERIAL = "material"
    IMMATERIAL = "immaterial"
    HIGH = "tinggi"
    MEDIUM = "sedang"
    LOW = "rendah"


RetrospectiveApplicationType = PSAK25ApplicationMethod
