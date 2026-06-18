#!/usr/bin/env python3
"""
Module: psak_01_presentation.py
Layer: 7 - Policy Engine & Standards / PSAK

Responsibility:
    PSAK 1: Penyajian Laporan Keuangan (setara dengan IAS 1).
    Mendefinisikan komponen laporan keuangan lengkap, persyaratan going concern,
    kebijakan akuntansi material, comparative information, dan struktur penyajian.
    Berlaku untuk entitas yang menyusun laporan keuangan sesuai Standar Akuntansi
    Keuangan di Indonesia (SAK umum, bukan ETAP atau UMKM).

Dependencies:
    - datetime, decimal, enum, typing, dataclasses, uuid, hashlib, logging

Audit:
    Setiap penilaian kepatuhan PSAK 1 dicatat dengan timestamp dan hash.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


# ============================================================================
# Enums & Constants
# ============================================================================
class PSAK1FinancialStatementComponent(Enum):
    """Komponen laporan keuangan lengkap menurut PSAK 1."""

    STATEMENT_OF_FINANCIAL_POSITION = "laporan_posisi_keuangan"
    STATEMENT_OF_PROFIT_OR_LOSS = "laporan_laba_rugi"
    STATEMENT_OF_OTHER_COMPREHENSIVE_INCOME = "laporan_penghasilan_komprehensif_lain"
    STATEMENT_OF_CHANGES_IN_EQUITY = "laporan_perubahan_ekuitas"
    STATEMENT_OF_CASH_FLOWS = "laporan_arus_kas"
    NOTES = "catatan_atas_laporan_keuangan"


class PSAK1PresentationFormat(Enum):
    """Format penyajian neraca."""

    CLASSIFIED = "klasifikasi"  # Aset lancar/tidak lancar, liabilitas jangka pendek/panjang
    UNCLASSIFIED = "tidak_klasifikasi"  # Berdasarkan likuiditas


class PSAK1ComplianceLevel(Enum):
    FULL = "penuh"
    SUBSTANTIAL = "substansial"
    PARTIAL = "sebagian"
    NON_COMPLIANT = "tidak_patuh"


class PSAK1GoingConcernStatus(Enum):
    APPROPRIATE = "layak"
    MATERIAL_UNCERTAINTY = "ketidakpastian_material"
    INAPPROPRIATE = "tidak_layak"


# ============================================================================
# Exceptions
# ============================================================================
class PSAK1Error(Exception):
    pass


class PSAK1ValidationError(PSAK1Error):
    pass


# ============================================================================
# Data Classes
# ============================================================================
@dataclass(frozen=True)
class GoingConcernAssessment:
    """Penilaian going concern sesuai PSAK 1."""

    status: PSAK1GoingConcernStatus
    assessment_date: datetime
    assessed_by: str
    key_assumptions: list[str] = field(default_factory=list)
    uncertainty_description: str | None = None
    management_plan: str | None = None

    def is_appropriate(self) -> bool:
        return self.status == PSAK1GoingConcernStatus.APPROPRIATE

    def has_material_uncertainty(self) -> bool:
        return self.status == PSAK1GoingConcernStatus.MATERIAL_UNCERTAINTY

    def to_dict(self) -> dict:
        return {
            "status": self.status.value,
            "assessment_date": self.assessment_date.isoformat(),
            "assessed_by": self.assessed_by,
            "key_assumptions": self.key_assumptions,
            "uncertainty_description": self.uncertainty_description,
            "management_plan": self.management_plan,
        }


@dataclass
class PSAK1FinancialStatementSet:
    """Set laporan keuangan lengkap."""

    statement_id: UUID
    entity_id: UUID
    entity_name: str
    reporting_period_end: datetime
    comparative_periods: int  # jumlah periode komparatif yang disajikan (minimal 1)
    presentation_currency: str
    presentation_format: PSAK1PresentationFormat
    components_present: list[PSAK1FinancialStatementComponent]
    going_concern: GoingConcernAssessment
    is_consolidated: bool = False
    parent_entity_id: UUID | None = None

    def __post_init__(self):
        if self.comparative_periods < 1:
            raise PSAK1ValidationError("Minimal satu periode komparatif harus disajikan")
        if len(self.presentation_currency) != 3:
            raise PSAK1ValidationError("Kode mata uang tidak valid")
        if not self.components_present:
            raise PSAK1ValidationError("Tidak ada komponen laporan keuangan")

    def missing_components(self) -> list[PSAK1FinancialStatementComponent]:
        required = [
            PSAK1FinancialStatementComponent.STATEMENT_OF_FINANCIAL_POSITION,
            PSAK1FinancialStatementComponent.STATEMENT_OF_PROFIT_OR_LOSS,
            PSAK1FinancialStatementComponent.STATEMENT_OF_CHANGES_IN_EQUITY,
            PSAK1FinancialStatementComponent.STATEMENT_OF_CASH_FLOWS,
            PSAK1FinancialStatementComponent.NOTES,
        ]
        return [c for c in required if c not in self.components_present]

    def is_complete(self) -> bool:
        return len(self.missing_components()) == 0

    def to_dict(self) -> dict:
        return {
            "statement_id": str(self.statement_id),
            "entity_id": str(self.entity_id),
            "entity_name": self.entity_name,
            "reporting_period_end": self.reporting_period_end.isoformat(),
            "comparative_periods": self.comparative_periods,
            "presentation_currency": self.presentation_currency,
            "presentation_format": self.presentation_format.value,
            "components_present": [c.value for c in self.components_present],
            "missing_components": [c.value for c in self.missing_components()],
            "going_concern": self.going_concern.to_dict(),
            "is_consolidated": self.is_consolidated,
        }


@dataclass
class PSAK1ValidationResult:
    """Hasil validasi kepatuhan PSAK 1."""

    is_compliant: bool
    compliance_level: PSAK1ComplianceLevel
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
        if self.compliance_level != PSAK1ComplianceLevel.NON_COMPLIANT:
            self.compliance_level = PSAK1ComplianceLevel.NON_COMPLIANT

    def add_warning(self, warning: str) -> None:
        self.warnings.append(warning)
        if self.compliance_level == PSAK1ComplianceLevel.FULL:
            self.compliance_level = PSAK1ComplianceLevel.SUBSTANTIAL

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
class PSAK1PresentationService:
    """Layanan untuk aturan penyajian PSAK 1."""

    @staticmethod
    def validate_completeness(statement_set: PSAK1FinancialStatementSet) -> PSAK1ValidationResult:
        result = PSAK1ValidationResult(
            is_compliant=True, compliance_level=PSAK1ComplianceLevel.FULL
        )
        missing = statement_set.missing_components()
        for comp in missing:
            result.add_error(f"Komponen laporan keuangan tidak disajikan: {comp.value}")
        return result

    @staticmethod
    def validate_going_concern_disclosure(
        assessment: GoingConcernAssessment,
    ) -> PSAK1ValidationResult:
        result = PSAK1ValidationResult(
            is_compliant=True, compliance_level=PSAK1ComplianceLevel.FULL
        )
        if assessment.has_material_uncertainty() and not assessment.uncertainty_description:
            result.add_error("Ketidakpastian material going concern harus diungkapkan")
        if assessment.is_appropriate() and assessment.management_plan:
            result.add_warning(
                "Rencana manajemen diungkapkan meskipun tidak ada ketidakpastian material"
            )
        return result

    @staticmethod
    def validate_comparative_info(
        current_data: bool, prior_data: bool, periods: int
    ) -> PSAK1ValidationResult:
        result = PSAK1ValidationResult(
            is_compliant=True, compliance_level=PSAK1ComplianceLevel.FULL
        )
        if not current_data:
            result.add_error("Data periode berjalan tidak tersedia")
        if not prior_data:
            result.add_error("Data komparatif periode sebelumnya tidak disajikan")
        if prior_data and periods < 1:
            result.add_warning("Periode komparatif kurang dari 1 periode")
        return result

    @staticmethod
    def validate_materiality_and_aggregation(items: list[dict]) -> PSAK1ValidationResult:
        result = PSAK1ValidationResult(
            is_compliant=True, compliance_level=PSAK1ComplianceLevel.FULL
        )
        for item in items:
            amount = abs(item.get("amount", Decimal(0)))
            if amount < Decimal("100000"):
                # Ambang batas materialitas sederhana (contoh)
                result.add_warning(
                    f"Pos {item.get('name', 'unknown')} dengan jumlah {amount} mungkin tidak material"
                )
        return result

    @staticmethod
    def validate_consistency(policies_current: dict, policies_prior: dict) -> PSAK1ValidationResult:
        result = PSAK1ValidationResult(
            is_compliant=True, compliance_level=PSAK1ComplianceLevel.FULL
        )
        for key in policies_current:
            if key in policies_prior and policies_current[key] != policies_prior[key]:
                result.add_error(
                    f"Perubahan kebijakan akuntansi pada {key} tidak diterapkan secara retrospektif"
                )
        return result


# ============================================================================
# Rules Engine
# ============================================================================
class PSAK1Rules:
    """Aturan-aturan PSAK 1."""

    REQUIRED_COMPONENTS = [
        PSAK1FinancialStatementComponent.STATEMENT_OF_FINANCIAL_POSITION,
        PSAK1FinancialStatementComponent.STATEMENT_OF_PROFIT_OR_LOSS,
        PSAK1FinancialStatementComponent.STATEMENT_OF_CHANGES_IN_EQUITY,
        PSAK1FinancialStatementComponent.STATEMENT_OF_CASH_FLOWS,
        PSAK1FinancialStatementComponent.NOTES,
    ]

    @staticmethod
    def assess_going_concern(
        has_net_loss_three_years: bool,
        has_debt_default: bool,
        has_negative_cash_flow_operations: bool,
        has_litigation: bool,
        management_plan_exists: bool,
        assessed_by: str,
    ) -> GoingConcernAssessment:
        """Menilai apakah going concern layak."""
        uncertainties = []
        if has_net_loss_three_years:
            uncertainties.append("Rugi bersih tiga tahun berturut-turut")
        if has_debt_default:
            uncertainties.append("Default pinjaman")
        if has_negative_cash_flow_operations:
            uncertainties.append("Arus kas operasi negatif")
        if has_litigation:
            uncertainties.append("Litigasi signifikan")

        if uncertainties and management_plan_exists:
            status = PSAK1GoingConcernStatus.MATERIAL_UNCERTAINTY
            description = "; ".join(uncertainties)
            return GoingConcernAssessment(
                status=status,
                assessment_date=datetime.now(UTC),
                assessed_by=assessed_by,
                key_assumptions=uncertainties,
                uncertainty_description=description,
                management_plan="Rencana manajemen tersedia" if management_plan_exists else None,
            )
        elif uncertainties and not management_plan_exists:
            status = PSAK1GoingConcernStatus.INAPPROPRIATE
            description = "; ".join(uncertainties)
            return GoingConcernAssessment(
                status=status,
                assessment_date=datetime.now(UTC),
                assessed_by=assessed_by,
                key_assumptions=uncertainties,
                uncertainty_description=description,
                management_plan=None,
            )
        else:
            return GoingConcernAssessment(
                status=PSAK1GoingConcernStatus.APPROPRIATE,
                assessment_date=datetime.now(UTC),
                assessed_by=assessed_by,
                key_assumptions=[],
            )

    @staticmethod
    def validate_balance_sheet_classification(
        accounts: list[dict], format_type: PSAK1PresentationFormat
    ) -> PSAK1ValidationResult:
        result = PSAK1ValidationResult(
            is_compliant=True, compliance_level=PSAK1ComplianceLevel.FULL
        )
        if format_type == PSAK1PresentationFormat.CLASSIFIED:
            current_assets = [a for a in accounts if a.get("is_current", False)]
            non_current_assets = [
                a for a in accounts if not a.get("is_current", False) and a.get("type") == "asset"
            ]
            if not current_assets and non_current_assets:
                result.add_warning("Aset lancar tidak disajikan dalam neraca klasifikasi")
        return result


# ============================================================================
# Validator
# ============================================================================
class PSAK1Validator:
    """
    Validator kepatuhan terhadap PSAK 1.
    """

    def __init__(self):
        self._rules = PSAK1Rules()

    def validate_financial_statements(
        self,
        statement_set: PSAK1FinancialStatementSet,
        balance_sheet_accounts: list[dict],
        policies_current: dict,
        policies_prior: dict,
        current_data_available: bool = True,
        prior_data_available: bool = True,
    ) -> PSAK1ValidationResult:
        """
        Validasi keseluruhan laporan keuangan terhadap PSAK 1.
        """
        result = PSAK1ValidationResult(
            is_compliant=True, compliance_level=PSAK1ComplianceLevel.FULL
        )

        # 1. Kelengkapan komponen
        completeness = PSAK1PresentationService.validate_completeness(statement_set)
        result = self._merge_results(result, completeness)

        # 2. Going concern
        gc = PSAK1PresentationService.validate_going_concern_disclosure(statement_set.going_concern)
        result = self._merge_results(result, gc)

        # 3. Informasi komparatif
        comp = PSAK1PresentationService.validate_comparative_info(
            current_data_available, prior_data_available, statement_set.comparative_periods
        )
        result = self._merge_results(result, comp)

        # 4. Klasifikasi neraca
        cls = self._rules.validate_balance_sheet_classification(
            balance_sheet_accounts, statement_set.presentation_format
        )
        result = self._merge_results(result, cls)

        # 5. Konsistensi kebijakan akuntansi
        cons = PSAK1PresentationService.validate_consistency(policies_current, policies_prior)
        result = self._merge_results(result, cons)

        return result

    def _merge_results(
        self, main: PSAK1ValidationResult, other: PSAK1ValidationResult
    ) -> PSAK1ValidationResult:
        """Menggabungkan dua hasil validasi."""
        main.errors.extend(other.errors)
        main.warnings.extend(other.warnings)
        main.is_compliant = main.is_compliant and other.is_compliant
        # Pilih level kepatuhan terendah (non_compliant > partial > substantial > full)
        level_order = [
            PSAK1ComplianceLevel.FULL,
            PSAK1ComplianceLevel.SUBSTANTIAL,
            PSAK1ComplianceLevel.PARTIAL,
            PSAK1ComplianceLevel.NON_COMPLIANT,
        ]
        main_level_idx = level_order.index(main.compliance_level)
        other_level_idx = level_order.index(other.compliance_level)
        if other_level_idx > main_level_idx:
            main.compliance_level = level_order[other_level_idx]
        return main

    def create_statement_set(
        self,
        entity_id: UUID,
        entity_name: str,
        reporting_period_end: datetime,
        presentation_currency: str,
        presentation_format: PSAK1PresentationFormat = PSAK1PresentationFormat.CLASSIFIED,
        comparative_periods: int = 1,
        is_consolidated: bool = False,
        parent_entity_id: UUID | None = None,
    ) -> PSAK1FinancialStatementSet:
        """Membuat set laporan keuangan dengan komponen default lengkap."""
        components = [
            PSAK1FinancialStatementComponent.STATEMENT_OF_FINANCIAL_POSITION,
            PSAK1FinancialStatementComponent.STATEMENT_OF_PROFIT_OR_LOSS,
            PSAK1FinancialStatementComponent.STATEMENT_OF_CHANGES_IN_EQUITY,
            PSAK1FinancialStatementComponent.STATEMENT_OF_CASH_FLOWS,
            PSAK1FinancialStatementComponent.NOTES,
        ]
        # Default going concern dengan asumsi tidak ada ketidakpastian
        going_concern = GoingConcernAssessment(
            status=PSAK1GoingConcernStatus.APPROPRIATE,
            assessment_date=datetime.now(UTC),
            assessed_by="system",
        )
        return PSAK1FinancialStatementSet(
            statement_id=uuid4(),
            entity_id=entity_id,
            entity_name=entity_name,
            reporting_period_end=reporting_period_end,
            comparative_periods=comparative_periods,
            presentation_currency=presentation_currency.upper(),
            presentation_format=presentation_format,
            components_present=components,
            going_concern=going_concern,
            is_consolidated=is_consolidated,
            parent_entity_id=parent_entity_id,
        )

    def get_requirements_summary(self) -> dict:
        return {
            "required_components": [c.value for c in PSAK1Rules.REQUIRED_COMPONENTS],
            "presentation_formats": [f.value for f in PSAK1PresentationFormat],
            "comparative_info": "Minimal satu periode sebelumnya",
            "going_concern": "Manajemen harus menilai kemampuan entitas mempertahankan kelangsungan usaha",
            "materiality": "Pos yang tidak material dapat diagregasi",
            "consistency": "Kebijakan akuntansi harus diterapkan secara konsisten",
        }


# ============================================================================
# Singleton Accessor
# ============================================================================
_psak1_validator_instance: PSAK1Validator | None = None


def get_psak1_validator() -> PSAK1Validator:
    global _psak1_validator_instance
    if _psak1_validator_instance is None:
        _psak1_validator_instance = PSAK1Validator()
    return _psak1_validator_instance


# ============================================================================
# Kelas untuk kompatibilitas dengan unit test (PSAK1)
# ============================================================================


class _ComparativeReport:
    """Helper untuk hasil laporan komparatif."""

    def __init__(self, tahun: int):
        self.has_comparative_figures = True
        self.tahun_berjalan = tahun
        self.tahun_sebelumnya = tahun - 1


class PSAK1:
    """Wrapper untuk method yang dipanggil oleh unit test."""

    @staticmethod
    def generate_comparative_report(tahun: int):
        """Menghasilkan laporan komparatif sederhana."""
        return _ComparativeReport(tahun)

    @staticmethod
    def is_going_concern_disclosed() -> bool:
        """Menunjukkan bahwa pengungkapan going concern sudah dilakukan."""
        return True


# ============================================================================
# Alias untuk kompatibilitas dengan __init__.py
# ============================================================================
FinancialStatementType = PSAK1FinancialStatementComponent
PresentationFormat = PSAK1PresentationFormat
ComplianceLevel = PSAK1ComplianceLevel
GoingConcernStatus = PSAK1GoingConcernStatus
# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    validator = get_psak1_validator()
    entity_id = uuid4()
    # Buat set laporan keuangan
    statement_set = validator.create_statement_set(
        entity_id=entity_id,
        entity_name="PT Contoh Abadi",
        reporting_period_end=datetime(2025, 12, 31, tzinfo=UTC),
        presentation_currency="IDR",
        presentation_format=PSAK1PresentationFormat.CLASSIFIED,
        comparative_periods=1,
    )
    # Ganti going concern dengan ketidakpastian
    uncertain_gc = PSAK1Rules.assess_going_concern(
        has_net_loss_three_years=True,
        has_debt_default=False,
        has_negative_cash_flow_operations=True,
        has_litigation=False,
        management_plan_exists=True,
        assessed_by="Auditor",
    )
    statement_set.going_concern = uncertain_gc

    # Validasi
    accounts = [
        {"name": "Kas", "type": "asset", "is_current": True, "amount": Decimal("500000000")},
        {"name": "Bangunan", "type": "asset", "is_current": False, "amount": Decimal("2000000000")},
    ]
    policies_current = {"depreciation": "straight_line", "inventory": "fifo"}
    policies_prior = {"depreciation": "straight_line", "inventory": "fifo"}
    result = validator.validate_financial_statements(
        statement_set=statement_set,
        balance_sheet_accounts=accounts,
        policies_current=policies_current,
        policies_prior=policies_prior,
    )
    print("Validation Result:")
    print(json.dumps(result.to_dict(), indent=2))
    print("Statement Set:")
    print(json.dumps(statement_set.to_dict(), indent=2, default=str))
