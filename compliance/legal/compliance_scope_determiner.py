#!/usr/bin/env python3
"""
Module: compliance_scope_determiner.py
Layer: Compliance / Legal

Responsibility:
    Menentukan lingkup kepatuhan (compliance scope) yang diperlukan berdasarkan
    yurisdiksi, sektor industri, jenis entitas (public/private/SME/startup),
    dan struktur grup. Menghasilkan daftar regulator yang relevan, kewajiban
    pelaporan, standar akuntansi yang berlaku, dan tenggat waktu default.

Dependencies:
    - datetime, typing, enum, hashlib, json, logging
    - dari modul ini: jurisdiction_definition (Jurisdiction), regulatory_body_registry (RegulatoryBody)

Audit:
    Setiap penentuan scope dicatat dengan timestamp dan hash.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4

from .jurisdiction_definition import Jurisdiction, JurisdictionDefinition
from .legal_exceptions import JurisdictionError
from .regulatory_body_registry import RegulatoryBody, RegulatoryBodyRegistry

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================
class EntityType(Enum):
    PUBLIC_LISTED = "public_listed"
    PRIVATE_LARGE = "private_large"
    PRIVATE_MEDIUM = "private_medium"
    SME = "sme"
    STARTUP = "startup"
    NON_PROFIT = "non_profit"
    GOVERNMENT = "government"


class IndustrySector(Enum):
    BANKING = "banking"
    FINANCE = "finance"
    INSURANCE = "insurance"
    CAPITAL_MARKET = "capital_market"
    MANUFACTURING = "manufacturing"
    TRADE = "trade"
    SERVICES = "services"
    CONSTRUCTION = "construction"
    PROPERTY = "property"
    MINING = "mining"
    AGRICULTURE = "agriculture"
    TECHNOLOGY = "technology"
    HEALTHCARE = "healthcare"
    EDUCATION = "education"
    TRANSPORTATION = "transportation"
    ENERGY = "energy"
    TELECOMMUNICATIONS = "telecommunications"
    MEDIA = "media"
    OTHER = "other"


class ReportingFrequency(Enum):
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    SEMI_ANNUAL = "semi_annual"
    ANNUAL = "annual"
    AD_HOC = "ad_hoc"


# ============================================================================
# Data Classes
# ============================================================================
class ComplianceRequirement:
    def __init__(
        self,
        requirement_id: UUID,
        title: str,
        regulatory_body: str,
        regulation: str,
        frequency: ReportingFrequency,
        due_day: int,
        due_month_offset: int,
        description: str,
        is_mandatory: bool = True,
        applicable_to: list[EntityType] | None = None,
    ):
        self.id = requirement_id
        self.title = title
        self.regulatory_body = regulatory_body
        self.regulation = regulation
        self.frequency = frequency
        self.due_day = due_day
        self.due_month_offset = due_month_offset
        self.description = description
        self.is_mandatory = is_mandatory
        self.applicable_to = applicable_to or []
        self.created_at = datetime.utcnow()
        self._hash = self._compute_hash()

    def _compute_hash(self) -> str:
        data = {
            "id": str(self.id),
            "title": self.title,
            "regulatory_body": self.regulatory_body,
            "frequency": self.frequency.value,
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "title": self.title,
            "regulatory_body": self.regulatory_body,
            "regulation": self.regulation,
            "frequency": self.frequency.value,
            "due_day": self.due_day,
            "due_month_offset": self.due_month_offset,
            "description": self.description,
            "is_mandatory": self.is_mandatory,
            "applicable_to": [et.value for et in self.applicable_to],
        }


class ComplianceScope:
    def __init__(
        self,
        jurisdiction: Jurisdiction,
        entity_type: EntityType,
        industry: IndustrySector,
        regulatory_bodies: list[RegulatoryBody],
        requirements: list[ComplianceRequirement],
        accounting_standards: list[str],
        tax_regime: str,
        audit_requirements: list[str],
        additional_notes: str = "",
    ):
        self.jurisdiction = jurisdiction
        self.entity_type = entity_type
        self.industry = industry
        self.regulatory_bodies = regulatory_bodies
        self.requirements = requirements
        self.accounting_standards = accounting_standards
        self.tax_regime = tax_regime
        self.audit_requirements = audit_requirements
        self.additional_notes = additional_notes
        self.determined_at = datetime.utcnow()
        self._hash = self._compute_hash()

    def _compute_hash(self) -> str:
        data = {
            "jurisdiction": self.jurisdiction.code,
            "entity_type": self.entity_type.value,
            "industry": self.industry.value,
            "regulatory_bodies": [b.code for b in self.regulatory_bodies],
            "accounting_standards": self.accounting_standards,
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    def to_dict(self) -> dict:
        return {
            "jurisdiction": {
                "code": self.jurisdiction.code,
                "name": self.jurisdiction.name,
                "legal_system": self.jurisdiction.legal_system,
            },
            "entity_type": self.entity_type.value,
            "industry": self.industry.value,
            "regulatory_bodies": [{"code": b.code, "name": b.name} for b in self.regulatory_bodies],
            "requirements": [r.to_dict() for r in self.requirements],
            "accounting_standards": self.accounting_standards,
            "tax_regime": self.tax_regime,
            "audit_requirements": self.audit_requirements,
            "additional_notes": self.additional_notes,
            "determined_at": self.determined_at.isoformat(),
            "hash": self._hash,
        }


# ============================================================================
# ComplianceScopeDeterminer Core
# ============================================================================
class ComplianceScopeDeterminer:
    """
    Menentukan lingkup kepatuhan berdasarkan yurisdiksi, jenis entitas, dan industri.
    """

    def __init__(self):
        self._jurisdiction_def = JurisdictionDefinition()
        self._regulatory_registry = RegulatoryBodyRegistry()
        self._requirements_cache: dict[str, list[ComplianceRequirement]] = {}
        self._init_default_requirements()

    def _init_default_requirements(self) -> None:
        """Mendefinisikan persyaratan kepatuhan default untuk berbagai yurisdiksi."""
        # Indonesia - OJK requirements
        self._add_requirement(
            ComplianceRequirement(
                requirement_id=uuid4(),
                title="Laporan Keuangan Publik Bulanan (LKPBU)",
                regulatory_body="OJK",
                regulation="POJK No. 29/POJK.04/2016",
                frequency=ReportingFrequency.MONTHLY,
                due_day=15,
                due_month_offset=0,
                description="Laporan keuangan untuk perusahaan publik",
                applicable_to=[EntityType.PUBLIC_LISTED],
            )
        )
        self._add_requirement(
            ComplianceRequirement(
                requirement_id=uuid4(),
                title="Laporan Tahunan (Annual Report)",
                regulatory_body="OJK",
                regulation="POJK No. 51/POJK.03/2017",
                frequency=ReportingFrequency.ANNUAL,
                due_day=30,
                due_month_offset=4,
                description="Laporan tahunan perusahaan publik",
                applicable_to=[EntityType.PUBLIC_LISTED, EntityType.PRIVATE_LARGE],
            )
        )
        # Indonesia - DJP requirements
        self._add_requirement(
            ComplianceRequirement(
                requirement_id=uuid4(),
                title="SPT Masa PPN",
                regulatory_body="DJP",
                regulation="UU PPN",
                frequency=ReportingFrequency.MONTHLY,
                due_day=20,
                due_month_offset=0,
                description="Pelaporan Pajak Pertambahan Nilai",
                applicable_to=[et for et in EntityType if et != EntityType.STARTUP],
            )
        )
        self._add_requirement(
            ComplianceRequirement(
                requirement_id=uuid4(),
                title="SPT Tahunan Badan",
                regulatory_body="DJP",
                regulation="UU PPh",
                frequency=ReportingFrequency.ANNUAL,
                due_day=30,
                due_month_offset=4,
                description="Pelaporan Pajak Penghasilan Badan",
                applicable_to=[et for et in EntityType if et != EntityType.NON_PROFIT],
            )
        )
        # Indonesia - BI requirements
        self._add_requirement(
            ComplianceRequirement(
                requirement_id=uuid4(),
                title="Laporan Transaksi Valuta Asing",
                regulatory_body="BI",
                regulation="PBI No. 18/9/PBI/2016",
                frequency=ReportingFrequency.MONTHLY,
                due_day=10,
                due_month_offset=0,
                description="Laporan transaksi devisa",
                applicable_to=[EntityType.BANKING, EntityType.FINANCE],
            )
        )
        # Singapore - MAS requirements
        self._add_requirement(
            ComplianceRequirement(
                requirement_id=uuid4(),
                title="Quarterly Financial Statements",
                regulatory_body="MAS",
                regulation="Companies Act",
                frequency=ReportingFrequency.QUARTERLY,
                due_day=30,
                due_month_offset=3,
                description="Laporan keuangan kuartalan",
                applicable_to=[EntityType.PUBLIC_LISTED],
            )
        )
        self._add_requirement(
            ComplianceRequirement(
                requirement_id=uuid4(),
                title="Annual Income Tax Filing (Form C)",
                regulatory_body="IRAS",
                regulation="Income Tax Act",
                frequency=ReportingFrequency.ANNUAL,
                due_day=30,
                due_month_offset=11,
                description="Tax filing for companies",
                applicable_to=[
                    EntityType.PUBLIC_LISTED,
                    EntityType.PRIVATE_LARGE,
                    EntityType.PRIVATE_MEDIUM,
                ],
            )
        )

    def _add_requirement(self, requirement: ComplianceRequirement) -> None:
        key = requirement.regulatory_body
        if key not in self._requirements_cache:
            self._requirements_cache[key] = []
        self._requirements_cache[key].append(requirement)

    def determine_scope(
        self,
        jurisdiction_code: str,
        entity_type: EntityType,
        industry: IndustrySector,
        is_consolidated_group: bool = False,
    ) -> ComplianceScope:
        """
        Menentukan lingkup kepatuhan untuk entitas.
        """
        # 1. Dapatkan yurisdiksi
        try:
            jur = self._jurisdiction_def.get_jurisdiction(jurisdiction_code)
        except ValueError as e:
            raise JurisdictionError(f"Jurisdiction {jurisdiction_code} not supported: {e}")

        # 2. Tentukan regulator berdasarkan industri dan yurisdiksi
        regulatory_bodies = self._determine_regulatory_bodies(jurisdiction_code, industry)

        # 3. Tentukan persyaratan kepatuhan yang berlaku
        requirements = self._determine_applicable_requirements(
            jurisdiction_code, entity_type, industry
        )

        # 4. Tentukan standar akuntansi
        accounting_standards = self._determine_accounting_standards(jurisdiction_code, entity_type)

        # 5. Tentukan regime pajak
        tax_regime = self._determine_tax_regime(jurisdiction_code, entity_type)

        # 6. Tentukan persyaratan audit
        audit_requirements = self._determine_audit_requirements(jurisdiction_code, entity_type)

        # 7. Catat lingkup untuk audit trail
        scope = ComplianceScope(
            jurisdiction=jur,
            entity_type=entity_type,
            industry=industry,
            regulatory_bodies=regulatory_bodies,
            requirements=requirements,
            accounting_standards=accounting_standards,
            tax_regime=tax_regime,
            audit_requirements=audit_requirements,
            additional_notes=self._generate_notes(
                jurisdiction_code, entity_type, industry, is_consolidated_group
            ),
        )
        logger.info(
            f"Compliance scope determined for {jurisdiction_code} - {entity_type.value} - {industry.value}"
        )
        return scope

    def _determine_regulatory_bodies(
        self, jurisdiction_code: str, industry: IndustrySector
    ) -> list[RegulatoryBody]:
        """Menentukan badan regulator yang relevan berdasarkan yurisdiksi dan industri."""
        bodies = []
        # Selalu sertakan otoritas pajak
        if jurisdiction_code == "ID":
            bodies.append(self._regulatory_registry.get_body("DJP"))
            bodies.append(
                self._regulatory_registry.get_body("OJK")
                if industry
                in [
                    IndustrySector.BANKING,
                    IndustrySector.FINANCE,
                    IndustrySector.INSURANCE,
                    IndustrySector.CAPITAL_MARKET,
                ]
                else None
            )
            bodies.append(
                self._regulatory_registry.get_body("BI")
                if industry in [IndustrySector.BANKING, IndustrySector.FINANCE]
                else None
            )
        elif jurisdiction_code == "SG":
            bodies.append(self._regulatory_registry.get_body("IRAS"))
            bodies.append(
                self._regulatory_registry.get_body("MAS")
                if industry
                in [IndustrySector.BANKING, IndustrySector.FINANCE, IndustrySector.INSURANCE]
                else None
            )
        elif jurisdiction_code == "US":
            bodies.append(self._regulatory_registry.get_body("IRS"))
            bodies.append(
                self._regulatory_registry.get_body("SEC")
                if industry == IndustrySector.CAPITAL_MARKET
                else None
            )
        # Filter None
        return [b for b in bodies if b is not None]

    def _determine_applicable_requirements(
        self,
        jurisdiction_code: str,
        entity_type: EntityType,
        industry: IndustrySector,
    ) -> list[ComplianceRequirement]:
        """Mengembalikan daftar persyaratan kepatuhan yang berlaku."""
        applicable = []
        for req_list in self._requirements_cache.values():
            for req in req_list:
                # Cek berdasarkan regulator dan yurisdiksi (sederhana)
                if (
                    (
                        (jurisdiction_code == "ID" and req.regulatory_body in ["OJK", "DJP", "BI"])
                        or (jurisdiction_code == "SG" and req.regulatory_body in ["MAS", "IRAS"])
                        or (jurisdiction_code == "US" and req.regulatory_body in ["SEC", "IRS"])
                    )
                    and (not req.applicable_to or entity_type in req.applicable_to)
                ):
                    applicable.append(req)
        return applicable

    def _determine_accounting_standards(
        self, jurisdiction_code: str, entity_type: EntityType
    ) -> list[str]:
        """Menentukan standar akuntansi yang berlaku."""
        if jurisdiction_code == "ID":
            if entity_type == EntityType.PUBLIC_LISTED:
                return [
                    "PSAK (IFRS converged)",
                    "SAK ETAP for SMEs" if entity_type == EntityType.SME else "SAK UMKM",
                ]
            else:
                return [
                    "PSAK Umum",
                    "SAK ETAP"
                    if entity_type == EntityType.SME
                    else "SAK UMKM"
                    if entity_type == EntityType.STARTUP
                    else "PSAK Umum",
                ]
        elif jurisdiction_code == "SG":
            return [
                "SFRS (Singapore FRS)",
                "SFRS for Small Entities"
                if entity_type in [EntityType.SME, EntityType.STARTUP]
                else "SFRS",
            ]
        elif jurisdiction_code == "US":
            return [
                "US GAAP",
                "IFRS for foreign private issuers"
                if entity_type == EntityType.PUBLIC_LISTED
                else "US GAAP",
            ]
        return ["IFRS"]

    def _determine_tax_regime(self, jurisdiction_code: str, entity_type: EntityType) -> str:
        """Menentukan regime perpajakan."""
        regimes = {
            "ID": {
                "default": "General (CIT 22%)",
                EntityType.SME: "SME facility (CIT 11% up to 4.8B)",
                EntityType.STARTUP: "Startup incentives (tax holiday) - subject to qualification",
            },
            "SG": {
                "default": "CIT 17% with partial exemption",
                EntityType.STARTUP: "Startup Tax Exemption (SUTE) for first 3 years",
            },
            "US": {
                "default": "Federal CIT 21% + state taxes",
            },
        }
        regime = regimes.get(jurisdiction_code, {}).get(
            entity_type, regimes.get(jurisdiction_code, {}).get("default", "Local tax regime")
        )
        return regime

    def _determine_audit_requirements(
        self, jurisdiction_code: str, entity_type: EntityType
    ) -> list[str]:
        """Menentukan persyaratan audit eksternal."""
        if entity_type == EntityType.PUBLIC_LISTED:
            return [
                "Annual audit by registered public accountant (KAP)",
                "Quarterly review for listed entities",
            ]
        elif entity_type in [EntityType.PRIVATE_LARGE, EntityType.PRIVATE_MEDIUM]:
            return ["Annual audit if exceeding certain asset/revenue thresholds"]
        else:
            return ["Audit not mandatory, but recommended for credibility"]

    def _generate_notes(
        self,
        jurisdiction_code: str,
        entity_type: EntityType,
        industry: IndustrySector,
        is_consolidated: bool,
    ) -> str:
        notes = []
        if is_consolidated:
            notes.append(
                "Consolidated group reporting may require additional disclosures per PSAK/IFRS 10"
            )
        if industry == IndustrySector.BANKING:
            notes.append(
                "Banking sector has additional capital adequacy (CAR) and liquidity reporting requirements"
            )
        if jurisdiction_code == "ID" and entity_type == EntityType.PUBLIC_LISTED:
            notes.append("Must comply with OJK regulations for public companies (POJK)")
        return " ".join(notes)

    def get_available_jurisdictions(self) -> list[str]:
        return [j.code for j in self._jurisdiction_def.get_all()]

    def get_requirements_summary(self) -> dict:
        total = sum(len(reqs) for reqs in self._requirements_cache.values())
        return {
            "total_requirements": total,
            "by_regulator": {reg: len(reqs) for reg, reqs in self._requirements_cache.items()},
        }

    def export_to_json(self, file_path: str) -> None:
        """Export compliance scope definition to JSON (for demo)."""
        data = {
            "jurisdictions": self.get_available_jurisdictions(),
            "requirements_summary": self.get_requirements_summary(),
            "requirements": [
                req.to_dict() for req_list in self._requirements_cache.values() for req in req_list
            ],
        }
        with open(file_path, "w") as f:
            json.dump(data, f, indent=2, default=str)
        logger.info(f"Exported compliance scope definitions to {file_path}")


# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    determiner = ComplianceScopeDeterminer()
    scope = determiner.determine_scope(
        jurisdiction_code="ID",
        entity_type=EntityType.PUBLIC_LISTED,
        industry=IndustrySector.MANUFACTURING,
        is_consolidated_group=True,
    )
    print("Compliance Scope:")
    print(json.dumps(scope.to_dict(), indent=2, default=str))
    determiner.export_to_json("compliance_scope.json")
