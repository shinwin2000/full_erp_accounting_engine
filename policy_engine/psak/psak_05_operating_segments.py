#!/usr/bin/env python3
"""
Module: psak_05_operating_segments.py
Layer: 7 - Policy Engine & Standards / PSAK

Responsibility:
    PSAK 5: Segmen Operasi (setara dengan IFRS 8).
    Mengatur pengungkapan informasi segmental untuk memungkinkan pengguna
    laporan keuangan mengevaluasi sifat dan dampak keuangan dari aktivitas
    bisnis dan lingkungan ekonomi tempat entitas beroperasi.
    Menerapkan pendekatan manajemen (management approach) sehingga informasi
    segmen disajikan berdasarkan laporan internal yang digunakan oleh
    pengambil keputusan operasional (chief operating decision maker - CODM).

Dependencies:
    - datetime, decimal, enum, typing, dataclasses, uuid, hashlib, logging

Audit:
    Setiap penetapan segmen dan pengungkapan dicatat dengan hash.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


# ============================================================================
# Enums & Constants
# ============================================================================
class PSAK5SegmentType(Enum):
    BUSINESS = "bisnis"
    GEOGRAPHICAL = "geografis"
    BOTH = "keduanya"


class PSAK5AggregationCriteria(Enum):
    SIMILAR_ECONOMIC_CHARACTERISTICS = "karakteristik_ekonomi_sama"
    SIMILAR_PRODUCTS = "produk_sama"
    SIMILAR_PRODUCTION = "proses_produksi_sama"
    SIMILAR_CUSTOMERS = "pelanggan_sama"
    SIMILAR_DISTRIBUTION = "distribusi_sama"


class PSAK5ComplianceLevel(Enum):
    FULL = "penuh"
    SUBSTANTIAL = "substansial"
    PARTIAL = "sebagian"
    NON_COMPLIANT = "tidak_patuh"


# ============================================================================
# Exceptions
# ============================================================================
class PSAK5Error(Exception):
    pass


class SegmentNotFoundError(PSAK5Error):
    pass


# ============================================================================
# Data Classes
# ============================================================================
@dataclass
class PSAK5Segment:
    """Segmen operasi tunggal."""

    segment_id: UUID
    segment_name: str
    segment_type: PSAK5SegmentType
    is_reportable: bool = True
    revenue_external: Decimal = Decimal(0)
    revenue_internal: Decimal = Decimal(0)
    total_revenue: Decimal = Decimal(0)
    profit_loss: Decimal = Decimal(0)
    assets: Decimal = Decimal(0)
    liabilities: Decimal = Decimal(0)
    capital_expenditure: Decimal = Decimal(0)
    depreciation: Decimal = Decimal(0)
    amortization: Decimal = Decimal(0)
    non_cash_expenses: Decimal = Decimal(0)

    def __post_init__(self):
        self.total_revenue = self.revenue_external + self.revenue_internal

    def compute_profit_margin(self) -> Decimal:
        if self.total_revenue == 0:
            return Decimal(0)
        return (self.profit_loss / self.total_revenue) * 100

    def to_dict(self) -> dict:
        return {
            "segment_id": str(self.segment_id),
            "segment_name": self.segment_name,
            "segment_type": self.segment_type.value,
            "is_reportable": self.is_reportable,
            "revenue_external": str(self.revenue_external),
            "revenue_internal": str(self.revenue_internal),
            "total_revenue": str(self.total_revenue),
            "profit_loss": str(self.profit_loss),
            "assets": str(self.assets),
            "liabilities": str(self.liabilities),
            "capital_expenditure": str(self.capital_expenditure),
            "depreciation": str(self.depreciation),
            "profit_margin": str(self.compute_profit_margin()),
        }


@dataclass
class PSAK5SegmentDisclosure:
    """Pengungkapan segmen secara agregat."""

    disclosure_id: UUID
    entity_id: UUID
    entity_name: str
    reporting_period_end: datetime
    segments: list[PSAK5Segment] = field(default_factory=list)
    aggregation_criteria_used: list[PSAK5AggregationCriteria] = field(default_factory=list)
    reconciliation_revenue: str | None = None
    reconciliation_profit_loss: str | None = None
    reconciliation_assets: str | None = None
    entity_wide_disclosures: dict[str, Any] = field(default_factory=dict)

    def total_external_revenue(self) -> Decimal:
        # FIX: tambahkan Decimal(0) sebagai nilai awal sum
        return sum((s.revenue_external for s in self.segments if s.is_reportable), Decimal(0))

    def total_reportable_segments(self) -> list[PSAK5Segment]:
        return [s for s in self.segments if s.is_reportable]

    def segment_count(self) -> int:
        return len(self.total_reportable_segments())

    def to_dict(self) -> dict:
        return {
            "disclosure_id": str(self.disclosure_id),
            "entity_id": str(self.entity_id),
            "entity_name": self.entity_name,
            "reporting_period_end": self.reporting_period_end.isoformat(),
            "segments": [s.to_dict() for s in self.segments],
            "aggregation_criteria": [c.value for c in self.aggregation_criteria_used],
            "total_external_revenue": str(self.total_external_revenue()),
            "segment_count": self.segment_count(),
            "reconciliation_revenue": self.reconciliation_revenue,
            "reconciliation_profit_loss": self.reconciliation_profit_loss,
            "entity_wide_disclosures": self.entity_wide_disclosures,
        }


@dataclass
class PSAK5ValidationResult:
    is_compliant: bool
    compliance_level: PSAK5ComplianceLevel
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
        if self.compliance_level != PSAK5ComplianceLevel.NON_COMPLIANT:
            self.compliance_level = PSAK5ComplianceLevel.NON_COMPLIANT

    def add_warning(self, warning: str) -> None:
        self.warnings.append(warning)
        if self.compliance_level == PSAK5ComplianceLevel.FULL:
            self.compliance_level = PSAK5ComplianceLevel.SUBSTANTIAL

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
class PSAK5SegmentService:
    """Service untuk identifikasi dan agregasi segmen."""

    @staticmethod
    def identify_reportable_segments(segments: list[PSAK5Segment]) -> list[PSAK5Segment]:
        """Mengidentifikasi segmen yang wajib dilaporkan berdasarkan threshold 10%."""
        total_external = sum((s.revenue_external for s in segments), Decimal(0))
        total_profit = sum((max(s.profit_loss, Decimal(0)) for s in segments), Decimal(0))
        total_assets = sum((s.assets for s in segments), Decimal(0))

        reportable = []
        for seg in segments:
            revenue_test = (
                (seg.revenue_external / total_external * 100) if total_external > 0 else Decimal(0)
            )
            profit_test = (
                (max(seg.profit_loss, Decimal(0)) / total_profit * 100) if total_profit > 0 else Decimal(0)
            )
            asset_test = (seg.assets / total_assets * 100) if total_assets > 0 else Decimal(0)
            if revenue_test >= 10 or profit_test >= 10 or asset_test >= 10:
                seg.is_reportable = True
                reportable.append(seg)
            else:
                seg.is_reportable = False
        return reportable

    @staticmethod
    def can_aggregate(
        segments: list[PSAK5Segment], criteria: list[PSAK5AggregationCriteria]
    ) -> bool:
        """Memeriksa apakah segmen-segmen dapat diagregasi."""
        if len(segments) <= 1:
            return True
        # Contoh sederhana: jika semua segmen memiliki tipe yang sama, boleh diagregasi
        types = {s.segment_type for s in segments}
        return len(types) == 1

    @staticmethod
    def compute_segment_reconciliation(
        segments: list[PSAK5Segment],
        total_entity_revenue: Decimal,
        total_entity_profit: Decimal,
        total_entity_assets: Decimal,
    ) -> dict[str, str]:
        """Menyusun rekonsiliasi total segmen ke entitas."""
        total_segment_revenue = sum((s.total_revenue for s in segments if s.is_reportable), Decimal(0))
        total_segment_profit = sum((s.profit_loss for s in segments if s.is_reportable), Decimal(0))
        total_segment_assets = sum((s.assets for s in segments if s.is_reportable), Decimal(0))
        return {
            "revenue": f"Total segmen {total_segment_revenue}, entitas {total_entity_revenue}, selisih {total_entity_revenue - total_segment_revenue}",
            "profit_loss": f"Total segmen {total_segment_profit}, entitas {total_entity_profit}, selisih {total_entity_profit - total_segment_profit}",
            "assets": f"Total segmen {total_segment_assets}, entitas {total_entity_assets}, selisih {total_entity_assets - total_segment_assets}",
        }


# ============================================================================
# Rules
# ============================================================================
class PSAK5Rules:
    """Aturan PSAK 5."""

    @staticmethod
    def validate_reportable_segments(segments: list[PSAK5Segment]) -> PSAK5ValidationResult:
        result = PSAK5ValidationResult(
            is_compliant=True, compliance_level=PSAK5ComplianceLevel.FULL
        )
        reportable = [s for s in segments if s.is_reportable]
        total_external = sum((s.revenue_external for s in reportable), Decimal(0))
        total_entity_revenue = max(total_external, sum((s.total_revenue for s in segments), Decimal(0)))
        if len(reportable) == 0:
            result.add_error("Tidak ada segmen yang memenuhi threshold 10%")
        elif (
            total_external / total_entity_revenue * 100 < 75 if total_entity_revenue > 0 else False
        ):
            result.add_warning(
                "Total pendapatan segmen kurang dari 75% pendapatan entitas, perlu tambahan segmen"
            )
        return result

    @staticmethod
    def validate_entity_wide_disclosures(
        segments: list[PSAK5Segment],
        has_product_disclosure: bool,
        has_geographic_disclosure: bool,
        has_major_customer_disclosure: bool,
    ) -> PSAK5ValidationResult:
        result = PSAK5ValidationResult(
            is_compliant=True, compliance_level=PSAK5ComplianceLevel.FULL
        )
        if not has_product_disclosure:
            result.add_error("Pengungkapan pendapatan per produk/jasa tidak disajikan")
        if not has_geographic_disclosure:
            result.add_error("Pengungkapan pendapatan per area geografis tidak disajikan")
        if not has_major_customer_disclosure:
            result.add_warning("Tidak ada pengungkapan pelanggan utama (≥10% pendapatan)")
        return result


# ============================================================================
# Validator
# ============================================================================
class PSAK5Validator:
    def __init__(self):
        self._rules = PSAK5Rules()
        self._service = PSAK5SegmentService()

    def create_segment(
        self,
        segment_name: str,
        segment_type: PSAK5SegmentType,
        revenue_external: Decimal = Decimal(0),
        revenue_internal: Decimal = Decimal(0),
        profit_loss: Decimal = Decimal(0),
        assets: Decimal = Decimal(0),
        liabilities: Decimal = Decimal(0),
    ) -> PSAK5Segment:
        return PSAK5Segment(
            segment_id=uuid4(),
            segment_name=segment_name,
            segment_type=segment_type,
            revenue_external=revenue_external,
            revenue_internal=revenue_internal,
            profit_loss=profit_loss,
            assets=assets,
            liabilities=liabilities,
        )

    def create_disclosure(
        self,
        entity_id: UUID,
        entity_name: str,
        reporting_period_end: datetime,
        segments: list[PSAK5Segment],
    ) -> PSAK5SegmentDisclosure:
        return PSAK5SegmentDisclosure(
            disclosure_id=uuid4(),
            entity_id=entity_id,
            entity_name=entity_name,
            reporting_period_end=reporting_period_end,
            segments=segments,
        )

    def identify_reportable_segments(
        self, disclosure: PSAK5SegmentDisclosure
    ) -> PSAK5SegmentDisclosure:
        reportable = self._service.identify_reportable_segments(disclosure.segments)
        new_segments = []
        for seg in disclosure.segments:
            if seg in reportable:
                seg.is_reportable = True
            new_segments.append(seg)
        return PSAK5SegmentDisclosure(
            disclosure_id=disclosure.disclosure_id,
            entity_id=disclosure.entity_id,
            entity_name=disclosure.entity_name,
            reporting_period_end=disclosure.reporting_period_end,
            segments=new_segments,
            aggregation_criteria_used=disclosure.aggregation_criteria_used,
            entity_wide_disclosures=disclosure.entity_wide_disclosures,
        )

    def compute_reconciliations(
        self,
        disclosure: PSAK5SegmentDisclosure,
        total_entity_revenue: Decimal,
        total_entity_profit: Decimal,
        total_entity_assets: Decimal,
    ) -> PSAK5SegmentDisclosure:
        rec = self._service.compute_segment_reconciliation(
            disclosure.segments, total_entity_revenue, total_entity_profit, total_entity_assets
        )
        return PSAK5SegmentDisclosure(
            disclosure_id=disclosure.disclosure_id,
            entity_id=disclosure.entity_id,
            entity_name=disclosure.entity_name,
            reporting_period_end=disclosure.reporting_period_end,
            segments=disclosure.segments,
            aggregation_criteria_used=disclosure.aggregation_criteria_used,
            reconciliation_revenue=rec["revenue"],
            reconciliation_profit_loss=rec["profit_loss"],
            reconciliation_assets=rec["assets"],
            entity_wide_disclosures=disclosure.entity_wide_disclosures,
        )

    def validate_disclosure(self, disclosure: PSAK5SegmentDisclosure) -> PSAK5ValidationResult:
        result = self._rules.validate_reportable_segments(disclosure.segments)
        # Additional validations for entity-wide disclosures
        has_product = "product" in str(
            disclosure.entity_wide_disclosures.get("product_disclosures", "")
        )
        has_geo = "geographic" in str(
            disclosure.entity_wide_disclosures.get("geographic_disclosures", "")
        )
        has_major = "major_customer" in str(
            disclosure.entity_wide_disclosures.get("major_customers", "")
        )
        result = self._merge_results(
            result,
            self._rules.validate_entity_wide_disclosures(
                disclosure.segments, has_product, has_geo, has_major
            ),
        )
        return result

    def _merge_results(
        self, main: PSAK5ValidationResult, other: PSAK5ValidationResult
    ) -> PSAK5ValidationResult:
        main.errors.extend(other.errors)
        main.warnings.extend(other.warnings)
        main.is_compliant = main.is_compliant and other.is_compliant
        level_order = [
            PSAK5ComplianceLevel.FULL,
            PSAK5ComplianceLevel.SUBSTANTIAL,
            PSAK5ComplianceLevel.PARTIAL,
            PSAK5ComplianceLevel.NON_COMPLIANT,
        ]
        main_idx = level_order.index(main.compliance_level)
        other_idx = level_order.index(other.compliance_level)
        if other_idx > main_idx:
            main.compliance_level = level_order[other_idx]
        return main

    def add_segment(
        self, disclosure: PSAK5SegmentDisclosure, segment: PSAK5Segment
    ) -> PSAK5SegmentDisclosure:
        new_segments = [*disclosure.segments, segment]
        return PSAK5SegmentDisclosure(
            disclosure_id=disclosure.disclosure_id,
            entity_id=disclosure.entity_id,
            entity_name=disclosure.entity_name,
            reporting_period_end=disclosure.reporting_period_end,
            segments=new_segments,
            aggregation_criteria_used=disclosure.aggregation_criteria_used,
            reconciliation_revenue=disclosure.reconciliation_revenue,
            reconciliation_profit_loss=disclosure.reconciliation_profit_loss,
            reconciliation_assets=disclosure.reconciliation_assets,
            entity_wide_disclosures=disclosure.entity_wide_disclosures,
        )

    def get_requirements_summary(self) -> dict:
        return {
            "threshold": "Segmen dengan pendapatan, laba, atau aset ≥10% dari total entitas harus dilaporkan",
            "minimum_coverage": "Segmen yang dilaporkan harus mencakup minimal 75% pendapatan eksternal",
            "entity_wide_disclosures": [
                "Pendapatan per produk/jasa",
                "Pendapatan per area geografis",
                "Ketergantungan pada pelanggan utama (≥10%)",
            ],
            "reconciliation": "Rekonsiliasi total segmen ke entitas",
        }


# ============================================================================
# Singleton Accessor
# ============================================================================
_psak5_validator_instance: PSAK5Validator | None = None


def get_psak5_validator() -> PSAK5Validator:
    global _psak5_validator_instance
    if _psak5_validator_instance is None:
        _psak5_validator_instance = PSAK5Validator()
    return _psak5_validator_instance


SegmentType = PSAK5SegmentType
OperatingSegment = PSAK5Segment


class SegmentReportableStatus(Enum):
    """Status apakah suatu segmen wajib dilaporkan."""

    REPORTABLE = "reportable"
    NON_REPORTABLE = "non_reportable"


# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    import json

    validator = get_psak5_validator()
    entity_id = uuid4()
    # Create segments
    seg1 = validator.create_segment(
        segment_name="Produk Elektronik",
        segment_type=PSAK5SegmentType.BUSINESS,
        revenue_external=Decimal("5000000000"),
        profit_loss=Decimal("800000000"),
        assets=Decimal("3000000000"),
    )
    seg2 = validator.create_segment(
        segment_name="Produk Furniture",
        segment_type=PSAK5SegmentType.BUSINESS,
        revenue_external=Decimal("2000000000"),
        profit_loss=Decimal("200000000"),
        assets=Decimal("1500000000"),
    )
    seg3 = validator.create_segment(
        segment_name="Jasa Konsultasi",
        segment_type=PSAK5SegmentType.BUSINESS,
        revenue_external=Decimal("300000000"),
        profit_loss=Decimal("50000000"),
        assets=Decimal("200000000"),
    )
    disclosure = validator.create_disclosure(
        entity_id=entity_id,
        entity_name="PT Contoh Segmentasi",
        reporting_period_end=datetime(2026, 12, 31, tzinfo=UTC),
        segments=[seg1, seg2, seg3],
    )
    # Add entity-wide disclosures
    disclosure.entity_wide_disclosures = {
        "product_disclosures": "Pendapatan: Elektronik 5M, Furniture 2M, Jasa 300jt",
        "geographic_disclosures": "Domestik 6.5M, Ekspor 800jt",
        "major_customers": "Pelanggan A (15%), Pelanggan B (12%)",
    }
    # Identify reportable segments
    disclosure = validator.identify_reportable_segments(disclosure)
    # Reconcile
    disclosure = validator.compute_reconciliations(
        disclosure,
        total_entity_revenue=Decimal("7300000000"),
        total_entity_profit=Decimal("1050000000"),
        total_entity_assets=Decimal("4700000000"),
    )
    # Validate
    result = validator.validate_disclosure(disclosure)
    print("Validation Result:")
    print(json.dumps(result.to_dict(), indent=2))
    print("\nDisclosure:")
    print(json.dumps(disclosure.to_dict(), indent=2, default=str))
