#!/usr/bin/env python3
"""
Module: psak_67_interests_in_other_entities.py
Layer: 7 - Policy Engine & Standards / PSAK

Responsibility:
    PSAK 67: Pengungkapan Kepentingan dalam Entitas Lain (setara dengan IFRS 12).
    Mengatur pengungkapan yang memungkinkan pengguna laporan keuangan
    mengevaluasi sifat, risiko, dan dampak keuangan dari kepentingan entitas
    dalam anak perusahaan, ventura bersama, asosiasi, dan entitas terstruktur
    yang tidak dikonsolidasi. Mencakup informasi tentang kepemilikan,
    kepentingan non-pengendali (NCI), pembatasan, dan komitmen.

Dependencies:
    - datetime, decimal, enum, typing, dataclasses, uuid, hashlib, logging

Audit:
    Setiap pengungkapan kepentingan dalam entitas lain dicatat.
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
# Enums
# ============================================================================
class PSAK67RelationshipType(Enum):
    SUBSIDIARY = "anak_perusahaan"
    JOINT_VENTURE = "ventura_bersama"
    ASSOCIATE = "asosiasi"
    STRUCTURED_ENTITY = "entitas_terstruktur"  # Tidak dikonsolidasi


class PSAK67NCIChoice(Enum):
    PROPORTIONATE_SHARE = "proporsi_aset_bersih"
    FAIR_VALUE = "nilai_wajar"


class PSAK67ControlAssessment(Enum):
    CONTROL = "pengendalian"
    JOINT_CONTROL = "pengendalian_bersama"
    SIGNIFICANT_INFLUENCE = "pengaruh_signifikan"
    NO_CONTROL = "tidak_ada_pengendalian"


class PSAK67RiskType(Enum):
    EXPOSURE_TO_LOSS = "eksposur_kerugian"
    FUNDING_COMMITMENT = "komitmen_pendanaan"
    CONTINGENT_LIABILITY = "liabilitas_kontinjensi"
    OTHER = "lainnya"


class PSAK67ComplianceLevel(Enum):
    FULL = "penuh"
    SUBSTANTIAL = "substansial"
    PARTIAL = "sebagian"
    NON_COMPLIANT = "tidak_patuh"


# ============================================================================
# Data Classes
# ============================================================================
@dataclass
class PSAK67OwnershipInterest:
    """Kepentingan kepemilikan dalam entitas lain."""

    ownership_id: UUID
    investee_id: UUID
    investee_name: str
    relationship_type: PSAK67RelationshipType
    ownership_percentage: Decimal  # 0-100
    voting_percentage: Decimal  # 0-100
    acquisition_date: datetime
    disposal_date: datetime | None = None
    control_assessment: PSAK67ControlAssessment = PSAK67ControlAssessment.NO_CONTROL
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "investee_id": str(self.investee_id),
            "investee_name": self.investee_name,
            "relationship": self.relationship_type.value,
            "ownership": str(self.ownership_percentage),
            "voting": str(self.voting_percentage),
            "acquisition_date": self.acquisition_date.isoformat(),
            "control_assessment": self.control_assessment.value,
        }


@dataclass
class PSAK67NonControllingInterest:
    """Kepentingan non-pengendali (NCI) dalam anak perusahaan."""

    nci_id: UUID
    subsidiary_id: UUID
    subsidiary_name: str
    nci_percentage: Decimal
    nci_measurement: PSAK67NCIChoice
    nci_amount: Decimal  # Nilai tercatat kepentingan non-pengendali
    profit_allocated_to_nci: Decimal = Decimal(0)
    dividends_paid_to_nci: Decimal = Decimal(0)
    other_comprehensive_income_allocated: Decimal = Decimal(0)

    def to_dict(self) -> dict:
        return {
            "subsidiary": self.subsidiary_name,
            "nci_percentage": str(self.nci_percentage),
            "measurement": self.nci_measurement.value,
            "nci_amount": str(self.nci_amount),
            "profit_allocated": str(self.profit_allocated_to_nci),
        }


@dataclass
class PSAK67StructuredEntity:
    """Entitas terstruktur yang tidak dikonsolidasi."""

    entity_id: UUID
    entity_name: str
    nature_of_relationship: str
    carrying_amount_assets: Decimal = Decimal(0)
    carrying_amount_liabilities: Decimal = Decimal(0)
    maximum_exposure_to_loss: Decimal = Decimal(0)
    funding_commitments: Decimal = Decimal(0)
    liquidity_agreements: str = ""

    def to_dict(self) -> dict:
        return {
            "entity_name": self.entity_name,
            "nature": self.nature_of_relationship,
            "assets": str(self.carrying_amount_assets),
            "liabilities": str(self.carrying_amount_liabilities),
            "max_loss_exposure": str(self.maximum_exposure_to_loss),
            "funding_commitments": str(self.funding_commitments),
        }


@dataclass
class PSAK67SignificantRestriction:
    """Pembatasan signifikan terhadap entitas."""

    restriction_id: UUID
    investee_id: UUID
    investee_name: str
    restriction_description: str
    affected_assets: str
    restricted_amount: Decimal

    def to_dict(self) -> dict:
        return {
            "investee": self.investee_name,
            "restriction": self.restriction_description,
            "affected_assets": self.affected_assets,
            "amount": str(self.restricted_amount),
        }


@dataclass
class PSAK67InterestsDisclosure:
    """Pengungkapan kepentingan dalam entitas lain."""

    disclosure_id: UUID
    entity_id: UUID
    entity_name: str
    reporting_date: datetime
    ownership_interests: list[PSAK67OwnershipInterest] = field(default_factory=list)
    non_controlling_interests: list[PSAK67NonControllingInterest] = field(default_factory=list)
    structured_entities: list[PSAK67StructuredEntity] = field(default_factory=list)
    restrictions: list[PSAK67SignificantRestriction] = field(default_factory=list)
    risks_from_structured_entities: list[tuple[PSAK67RiskType, str]] = field(default_factory=list)
    summary_of_subsidiaries: str = ""
    summary_of_associates: str = ""

    def total_nci_amount(self) -> Decimal:
        # FIX: gunakan Decimal(0) sebagai nilai awal sum
        return sum((nci.nci_amount for nci in self.non_controlling_interests), Decimal(0))

    def total_structured_entity_assets(self) -> Decimal:
        return sum((se.carrying_amount_assets for se in self.structured_entities), Decimal(0))

    def total_commitments_to_structured_entities(self) -> Decimal:
        return sum((se.funding_commitments for se in self.structured_entities), Decimal(0))

    def to_dict(self) -> dict:
        return {
            "disclosure_id": str(self.disclosure_id),
            "entity_id": str(self.entity_id),
            "entity_name": self.entity_name,
            "reporting_date": self.reporting_date.isoformat(),
            "ownership_interests": [oi.to_dict() for oi in self.ownership_interests],
            "non_controlling_interests": [nci.to_dict() for nci in self.non_controlling_interests],
            "structured_entities": [se.to_dict() for se in self.structured_entities],
            "restrictions": [r.to_dict() for r in self.restrictions],
            "risks": [
                {"type": rt.value, "description": desc}
                for rt, desc in self.risks_from_structured_entities
            ],
            "total_nci": str(self.total_nci_amount()),
            "total_structured_assets": str(self.total_structured_entity_assets()),
            "total_commitments_structured": str(self.total_commitments_to_structured_entities()),
        }


@dataclass
class PSAK67ValidationResult:
    is_compliant: bool
    compliance_level: PSAK67ComplianceLevel
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
        if self.compliance_level != PSAK67ComplianceLevel.NON_COMPLIANT:
            self.compliance_level = PSAK67ComplianceLevel.NON_COMPLIANT

    def add_warning(self, warning: str) -> None:
        self.warnings.append(warning)
        if self.compliance_level == PSAK67ComplianceLevel.FULL:
            self.compliance_level = PSAK67ComplianceLevel.SUBSTANTIAL

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
class PSAK67InterestService:
    """Service untuk pengungkapan kepentingan dalam entitas lain."""

    @staticmethod
    def assess_control(
        ownership_percentage: Decimal,
        voting_percentage: Decimal,
        has_contractual_control: bool,
        has_power_over_key_decisions: bool,
    ) -> PSAK67ControlAssessment:
        if ownership_percentage > 50 or voting_percentage > 50 or has_contractual_control:
            return PSAK67ControlAssessment.CONTROL
        elif has_power_over_key_decisions:
            return PSAK67ControlAssessment.JOINT_CONTROL
        elif 20 <= ownership_percentage <= 50:
            return PSAK67ControlAssessment.SIGNIFICANT_INFLUENCE
        else:
            return PSAK67ControlAssessment.NO_CONTROL

    @staticmethod
    def is_structured_entity(voting_rights_exist: bool, independent_powers: bool) -> bool:
        """Kriteria entitas terstruktur (tidak memiliki hak suara atau tidak independent)."""
        return not voting_rights_exist or not independent_powers


# ============================================================================
# Rules
# ============================================================================
class PSAK67Rules:
    """Aturan PSAK 67."""

    @staticmethod
    def validate_ownership_interest(oi: PSAK67OwnershipInterest) -> PSAK67ValidationResult:
        result = PSAK67ValidationResult(
            is_compliant=True, compliance_level=PSAK67ComplianceLevel.FULL
        )
        if oi.ownership_percentage < 0 or oi.ownership_percentage > 100:
            result.add_error("Persentase kepemilikan tidak valid")
        if (
            oi.relationship_type == PSAK67RelationshipType.SUBSIDIARY
            and oi.control_assessment != PSAK67ControlAssessment.CONTROL
        ):
            result.add_warning(
                "Entitas diklasifikasikan sebagai anak perusahaan tetapi kontrol tidak terpenuhi"
            )
        return result

    @staticmethod
    def validate_nci_disclosure(nci: PSAK67NonControllingInterest) -> PSAK67ValidationResult:
        result = PSAK67ValidationResult(
            is_compliant=True, compliance_level=PSAK67ComplianceLevel.FULL
        )
        if nci.nci_percentage > 0 and nci.nci_amount <= 0:
            result.add_warning("Kepentingan non-pengendali positif dengan nilai nol atau negatif")
        return result

    @staticmethod
    def validate_structured_entity(se: PSAK67StructuredEntity) -> PSAK67ValidationResult:
        result = PSAK67ValidationResult(
            is_compliant=True, compliance_level=PSAK67ComplianceLevel.FULL
        )
        if se.maximum_exposure_to_loss < se.carrying_amount_assets:
            result.add_warning("Eksposur maksimum kerugian kurang dari nilai tercatat aset")
        return result

    @staticmethod
    def validate_restriction_disclosure(
        restriction: PSAK67SignificantRestriction,
    ) -> PSAK67ValidationResult:
        result = PSAK67ValidationResult(
            is_compliant=True, compliance_level=PSAK67ComplianceLevel.FULL
        )
        if restriction.restricted_amount < 0:
            result.add_error("Nilai aset yang direstriksi tidak boleh negatif")
        return result


# ============================================================================
# Validator
# ============================================================================
class PSAK67Validator:
    def __init__(self):
        self._rules = PSAK67Rules()
        self._service = PSAK67InterestService()

    def create_ownership_interest(
        self,
        investee_id: UUID,
        investee_name: str,
        relationship_type: PSAK67RelationshipType,
        ownership_percentage: Decimal,
        voting_percentage: Decimal,
        acquisition_date: datetime,
        has_contractual_control: bool = False,
        has_power_over_key_decisions: bool = False,
    ) -> PSAK67OwnershipInterest:
        control = self._service.assess_control(
            ownership_percentage,
            voting_percentage,
            has_contractual_control,
            has_power_over_key_decisions,
        )
        return PSAK67OwnershipInterest(
            ownership_id=uuid4(),
            investee_id=investee_id,
            investee_name=investee_name,
            relationship_type=relationship_type,
            ownership_percentage=ownership_percentage,
            voting_percentage=voting_percentage,
            acquisition_date=acquisition_date,
            control_assessment=control,
        )

    def create_non_controlling_interest(
        self,
        subsidiary_id: UUID,
        subsidiary_name: str,
        nci_percentage: Decimal,
        nci_measurement: PSAK67NCIChoice,
        nci_amount: Decimal,
        profit_allocated: Decimal = Decimal(0),
        dividends_paid: Decimal = Decimal(0),
    ) -> PSAK67NonControllingInterest:
        return PSAK67NonControllingInterest(
            nci_id=uuid4(),
            subsidiary_id=subsidiary_id,
            subsidiary_name=subsidiary_name,
            nci_percentage=nci_percentage,
            nci_measurement=nci_measurement,
            nci_amount=nci_amount,
            profit_allocated_to_nci=profit_allocated,
            dividends_paid_to_nci=dividends_paid,
        )

    def create_structured_entity(
        self,
        entity_name: str,
        nature_of_relationship: str,
        carrying_amount_assets: Decimal = Decimal(0),
        carrying_amount_liabilities: Decimal = Decimal(0),
        maximum_exposure_to_loss: Decimal = Decimal(0),
        funding_commitments: Decimal = Decimal(0),
        liquidity_agreements: str = "",
    ) -> PSAK67StructuredEntity:
        return PSAK67StructuredEntity(
            entity_id=uuid4(),
            entity_name=entity_name,
            nature_of_relationship=nature_of_relationship,
            carrying_amount_assets=carrying_amount_assets,
            carrying_amount_liabilities=carrying_amount_liabilities,
            maximum_exposure_to_loss=max(maximum_exposure_to_loss, carrying_amount_assets),
            funding_commitments=funding_commitments,
            liquidity_agreements=liquidity_agreements,
        )

    def create_restriction(
        self,
        investee_id: UUID,
        investee_name: str,
        restriction_description: str,
        affected_assets: str,
        restricted_amount: Decimal,
    ) -> PSAK67SignificantRestriction:
        return PSAK67SignificantRestriction(
            restriction_id=uuid4(),
            investee_id=investee_id,
            investee_name=investee_name,
            restriction_description=restriction_description,
            affected_assets=affected_assets,
            restricted_amount=restricted_amount,
        )

    def create_disclosure(
        self,
        entity_id: UUID,
        entity_name: str,
        reporting_date: datetime,
    ) -> PSAK67InterestsDisclosure:
        return PSAK67InterestsDisclosure(
            disclosure_id=uuid4(),
            entity_id=entity_id,
            entity_name=entity_name,
            reporting_date=reporting_date,
        )

    def add_ownership_interest(
        self, disclosure: PSAK67InterestsDisclosure, oi: PSAK67OwnershipInterest
    ) -> PSAK67InterestsDisclosure:
        new_list = [*disclosure.ownership_interests, oi]
        return PSAK67InterestsDisclosure(
            disclosure_id=disclosure.disclosure_id,
            entity_id=disclosure.entity_id,
            entity_name=disclosure.entity_name,
            reporting_date=disclosure.reporting_date,
            ownership_interests=new_list,
            non_controlling_interests=disclosure.non_controlling_interests,
            structured_entities=disclosure.structured_entities,
            restrictions=disclosure.restrictions,
            risks_from_structured_entities=disclosure.risks_from_structured_entities,
            summary_of_subsidiaries=disclosure.summary_of_subsidiaries,
            summary_of_associates=disclosure.summary_of_associates,
        )

    def add_nci(
        self, disclosure: PSAK67InterestsDisclosure, nci: PSAK67NonControllingInterest
    ) -> PSAK67InterestsDisclosure:
        new_list = [*disclosure.non_controlling_interests, nci]
        return PSAK67InterestsDisclosure(
            disclosure_id=disclosure.disclosure_id,
            entity_id=disclosure.entity_id,
            entity_name=disclosure.entity_name,
            reporting_date=disclosure.reporting_date,
            ownership_interests=disclosure.ownership_interests,
            non_controlling_interests=new_list,
            structured_entities=disclosure.structured_entities,
            restrictions=disclosure.restrictions,
            risks_from_structured_entities=disclosure.risks_from_structured_entities,
            summary_of_subsidiaries=disclosure.summary_of_subsidiaries,
            summary_of_associates=disclosure.summary_of_associates,
        )

    def add_structured_entity(
        self, disclosure: PSAK67InterestsDisclosure, se: PSAK67StructuredEntity
    ) -> PSAK67InterestsDisclosure:
        new_list = [*disclosure.structured_entities, se]
        return PSAK67InterestsDisclosure(
            disclosure_id=disclosure.disclosure_id,
            entity_id=disclosure.entity_id,
            entity_name=disclosure.entity_name,
            reporting_date=disclosure.reporting_date,
            ownership_interests=disclosure.ownership_interests,
            non_controlling_interests=disclosure.non_controlling_interests,
            structured_entities=new_list,
            restrictions=disclosure.restrictions,
            risks_from_structured_entities=disclosure.risks_from_structured_entities,
            summary_of_subsidiaries=disclosure.summary_of_subsidiaries,
            summary_of_associates=disclosure.summary_of_associates,
        )

    def add_restriction(
        self, disclosure: PSAK67InterestsDisclosure, restriction: PSAK67SignificantRestriction
    ) -> PSAK67InterestsDisclosure:
        new_list = [*disclosure.restrictions, restriction]
        return PSAK67InterestsDisclosure(
            disclosure_id=disclosure.disclosure_id,
            entity_id=disclosure.entity_id,
            entity_name=disclosure.entity_name,
            reporting_date=disclosure.reporting_date,
            ownership_interests=disclosure.ownership_interests,
            non_controlling_interests=disclosure.non_controlling_interests,
            structured_entities=disclosure.structured_entities,
            restrictions=new_list,
            risks_from_structured_entities=disclosure.risks_from_structured_entities,
            summary_of_subsidiaries=disclosure.summary_of_subsidiaries,
            summary_of_associates=disclosure.summary_of_associates,
        )

    def add_risk(
        self, disclosure: PSAK67InterestsDisclosure, risk_type: PSAK67RiskType, description: str
    ) -> PSAK67InterestsDisclosure:
        new_list = [*disclosure.risks_from_structured_entities, (risk_type, description)]
        return PSAK67InterestsDisclosure(
            disclosure_id=disclosure.disclosure_id,
            entity_id=disclosure.entity_id,
            entity_name=disclosure.entity_name,
            reporting_date=disclosure.reporting_date,
            ownership_interests=disclosure.ownership_interests,
            non_controlling_interests=disclosure.non_controlling_interests,
            structured_entities=disclosure.structured_entities,
            restrictions=disclosure.restrictions,
            risks_from_structured_entities=new_list,
            summary_of_subsidiaries=disclosure.summary_of_subsidiaries,
            summary_of_associates=disclosure.summary_of_associates,
        )

    def validate_disclosure(self, disclosure: PSAK67InterestsDisclosure) -> PSAK67ValidationResult:
        result = PSAK67ValidationResult(
            is_compliant=True, compliance_level=PSAK67ComplianceLevel.FULL
        )
        for oi in disclosure.ownership_interests:
            result = self._merge_results(result, self._rules.validate_ownership_interest(oi))
        for nci in disclosure.non_controlling_interests:
            result = self._merge_results(result, self._rules.validate_nci_disclosure(nci))
        for se in disclosure.structured_entities:
            result = self._merge_results(result, self._rules.validate_structured_entity(se))
        for r in disclosure.restrictions:
            result = self._merge_results(result, self._rules.validate_restriction_disclosure(r))
        return result

    def _merge_results(
        self, main: PSAK67ValidationResult, other: PSAK67ValidationResult
    ) -> PSAK67ValidationResult:
        main.errors.extend(other.errors)
        main.warnings.extend(other.warnings)
        main.is_compliant = main.is_compliant and other.is_compliant
        level_order = [
            PSAK67ComplianceLevel.FULL,
            PSAK67ComplianceLevel.SUBSTANTIAL,
            PSAK67ComplianceLevel.PARTIAL,
            PSAK67ComplianceLevel.NON_COMPLIANT,
        ]
        main_idx = level_order.index(main.compliance_level)
        other_idx = level_order.index(other.compliance_level)
        if other_idx > main_idx:
            main.compliance_level = level_order[other_idx]
        return main

    def get_requirements_summary(self) -> dict:
        return {
            "objective": "Pengguna laporan keuangan dapat mengevaluasi sifat, risiko, dan dampak keuangan dari kepentingan entitas dalam entitas lain",
            "disclosures_for_subsidiaries": [
                "Sifat hubungan dengan anak perusahaan",
                "Kepentingan non-pengendali (NCI)",
                "Informasi ringkas keuangan anak perusahaan yang material",
                "Pembatasan signifikan atas kemampuan anak perusahaan",
                "Komitmen untuk mendukung anak perusahaan",
            ],
            "disclosures_for_joint_ventures_and_associates": [
                "Sifat hubungan",
                "Persentase kepemilikan",
                "Metode akuntansi yang digunakan (metode ekuitas)",
                "Nilai tercatat investasi",
                "Informasi ringkas keuangan (ringkasan aset, liabilitas, pendapatan, laba rugi)",
            ],
            "disclosures_for_structured_entities": [
                "Sifat entitas terstruktur",
                "Nilai tercatat aset dan liabilitas",
                "Eksposur maksimum terhadap kerugian",
                "Komitmen pendanaan dan perjanjian likuiditas",
                "Pendapatan yang diakui dari entitas terstruktur",
            ],
            "risks": "Risiko dari kepentingan dalam entitas terstruktur",
        }


# ============================================================================
# Singleton Accessor
# ============================================================================
_psak67_validator_instance: PSAK67Validator | None = None


def get_psak67_validator() -> PSAK67Validator:
    global _psak67_validator_instance
    if _psak67_validator_instance is None:
        _psak67_validator_instance = PSAK67Validator()
    return _psak67_validator_instance


# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    import json

    validator = get_psak67_validator()
    entity_id = uuid4()

    disclosure = validator.create_disclosure(
        entity_id=entity_id,
        entity_name="PT Induk Sejahtera",
        reporting_date=datetime(2026, 12, 31, tzinfo=UTC),
    )

    # Subsidiary (100% owned)
    sub = validator.create_ownership_interest(
        investee_id=uuid4(),
        investee_name="PT Anak Maju",
        relationship_type=PSAK67RelationshipType.SUBSIDIARY,
        ownership_percentage=Decimal("100"),
        voting_percentage=Decimal("100"),
        acquisition_date=datetime(2020, 1, 1, tzinfo=UTC),
        has_contractual_control=True,
    )
    disclosure = validator.add_ownership_interest(disclosure, sub)

    # Associate (25% owned)
    assoc = validator.create_ownership_interest(
        investee_id=uuid4(),
        investee_name="PT Mitra Kerja",
        relationship_type=PSAK67RelationshipType.ASSOCIATE,
        ownership_percentage=Decimal("25"),
        voting_percentage=Decimal("25"),
        acquisition_date=datetime(2022, 6, 1, tzinfo=UTC),
    )
    disclosure = validator.add_ownership_interest(disclosure, assoc)

    # NCI for subsidiary (if less than 100%)
    nci = validator.create_non_controlling_interest(
        subsidiary_id=sub.investee_id,
        subsidiary_name="PT Anak Maju",
        nci_percentage=Decimal("0"),  # 100% owned, no NCI
        nci_measurement=PSAK67NCIChoice.PROPORTIONATE_SHARE,
        nci_amount=Decimal("0"),
    )
    disclosure = validator.add_nci(disclosure, nci)

    # Structured entity
    se = validator.create_structured_entity(
        entity_name="Dana Investasi XYZ",
        nature_of_relationship="Entitas terstruktur di mana perusahaan memiliki kepentingan variabel",
        carrying_amount_assets=Decimal("5000000000"),
        carrying_amount_liabilities=Decimal("4500000000"),
        maximum_exposure_to_loss=Decimal("500000000"),
        funding_commitments=Decimal("100000000"),
        liquidity_agreements="Perusahaan berkomitmen menyediakan likuiditas hingga 100M",
    )
    disclosure = validator.add_structured_entity(disclosure, se)

    # Restriction
    restriction = validator.create_restriction(
        investee_id=sub.investee_id,
        investee_name="PT Anak Maju",
        restriction_description="Anak perusahaan tidak dapat membagikan dividen karena pembatasan perjanjian pinjaman",
        affected_assets="Laba ditahan",
        restricted_amount=Decimal("200000000"),
    )
    disclosure = validator.add_restriction(disclosure, restriction)

    # Risk
    disclosure = validator.add_risk(
        disclosure,
        PSAK67RiskType.EXPOSURE_TO_LOSS,
        "Eksposur kerugian dari entitas terstruktur hingga 500M",
    )

    # Summaries
    disclosure.summary_of_subsidiaries = (
        "PT Anak Maju (100%): total aset 10M, liabilitas 5M, laba 1M"
    )
    disclosure.summary_of_associates = (
        "PT Mitra Kerja (25%): total aset 8M, liabilitas 3M, laba 800M"
    )

    # Validate
    result = validator.validate_disclosure(disclosure)
    print("Validation Result:")
    print(json.dumps(result.to_dict(), indent=2))
    print("\nDisclosure:")
    print(json.dumps(disclosure.to_dict(), indent=2, default=str))


# ============================================================================
# Compatibility Aliases for Orchestration / Aggregator Core (PSAK 67)
# ============================================================================
# Only one block to avoid duplicate definitions
InterestType = PSAK67RelationshipType
ControlLevel = PSAK67ControlAssessment
StructuredEntity = PSAK67StructuredEntity
InterestInOtherEntity = PSAK67InterestsDisclosure
