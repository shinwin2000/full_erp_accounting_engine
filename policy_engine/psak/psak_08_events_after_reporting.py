#!/usr/bin/env python3
"""
Module: psak_08_events_after_reporting.py
Layer: 7 - Policy Engine & Standards / PSAK

Responsibility:
    PSAK 8: Peristiwa Setelah Periode Pelaporan (setara dengan IAS 10).
    Mengatur perlakuan akuntansi dan pengungkapan untuk peristiwa yang terjadi
    antara akhir periode pelaporan dan tanggal penyelesaian laporan keuangan.
    Peristiwa diklasifikasikan menjadi dua jenis: penyesuaian (adjusting events)
    yang memberikan bukti tambahan tentang kondisi yang sudah ada pada akhir periode,
    dan non-penyesuaian (non-adjusting events) yang mengindikasikan kondisi baru
    yang timbul setelah periode pelaporan.

Dependencies:
    - datetime, decimal, enum, typing, dataclasses, uuid, hashlib, logging

Audit:
    Setiap peristiwa yang diidentifikasi dan klasifikasinya dicatat dengan hash.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================
class EventType(Enum):
    """Jenis peristiwa setelah periode pelaporan."""

    ADJUSTING = "penyesuaian"
    NON_ADJUSTING = "non_penyesuaian"


class EventCategory(Enum):
    """Kategori peristiwa umum."""

    SETTLEMENT_OF_COURT_CASE = "penyelesaian_kasus_hukum"
    BANKRUPTCY = "kebangkrutan"
    SALE_OF_INVENTORY = "penjualan_persediaan"
    DECLINE_IN_MARKET_VALUE = "penurunan_nilai_pasar"
    DECLARATION_OF_DIVIDEND = "deklarasi_dividen"
    MAJOR_BUSINESS_COMBINATION = "kombinasi_bisnis_besar"
    MAJOR_PURCHASE_OF_ASSETS = "pembelian_aset_besar"
    DESTRUCTION_OF_ASSETS = "kerusakan_aset"
    CHANGES_IN_TAX_RATES = "perubahan_tarif_pajak"
    CHANGES_IN_EXCHANGE_RATES = "perubahan_kurs"
    FRAUD_OR_ERRORS = "kecurangan_atau_kesalahan"
    GOING_CONCERN_ISSUES = "masalah_going_concern"
    OTHER = "lainnya"


class PSAK8ComplianceLevel(Enum):
    FULL = "penuh"
    SUBSTANTIAL = "substansial"
    PARTIAL = "sebagian"
    NON_COMPLIANT = "tidak_patuh"


# ============================================================================
# Exceptions
# ============================================================================
class PSAK8Error(Exception):
    pass


class EventNotFoundError(PSAK8Error):
    pass


# ============================================================================
# Data Classes
# ============================================================================
@dataclass
class AfterReportingPeriodEvent:
    """Peristiwa setelah periode pelaporan."""

    event_id: UUID
    event_description: str
    event_date: date
    event_type: EventType
    category: EventCategory
    financial_impact: Decimal = Decimal(0)
    currency: str = "IDR"
    disclosure_required: bool = True
    adjustment_journal_reference: str | None = None
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "event_id": str(self.event_id),
            "event_description": self.event_description,
            "event_date": self.event_date.isoformat(),
            "event_type": self.event_type.value,
            "category": self.category.value,
            "financial_impact": str(self.financial_impact),
            "currency": self.currency,
            "disclosure_required": self.disclosure_required,
            "adjustment_journal": self.adjustment_journal_reference,
            "notes": self.notes,
        }


@dataclass
class AfterReportingPeriodDisclosure:
    """Pengungkapan peristiwa setelah periode pelaporan."""

    disclosure_id: UUID
    entity_id: UUID
    entity_name: str
    reporting_period_end: date
    financial_statements_authorized_date: date
    events: list[AfterReportingPeriodEvent] = field(default_factory=list)
    adjustment_events: list[AfterReportingPeriodEvent] = field(default_factory=list)
    non_adjustment_events: list[AfterReportingPeriodEvent] = field(default_factory=list)
    going_concern_assessment_revised: bool = False
    going_concern_disclosure: str = ""

    def __post_init__(self):
        # Auto-classify events
        self.adjustment_events = [e for e in self.events if e.event_type == EventType.ADJUSTING]
        self.non_adjustment_events = [
            e for e in self.events if e.event_type == EventType.NON_ADJUSTING
        ]

    def total_adjustment_impact(self) -> Decimal:
        return sum(e.financial_impact for e in self.adjustment_events)

    def total_non_adjustment_impact(self) -> Decimal:
        return sum(e.financial_impact for e in self.non_adjustment_events)

    def to_dict(self) -> dict:
        return {
            "disclosure_id": str(self.disclosure_id),
            "entity_id": str(self.entity_id),
            "entity_name": self.entity_name,
            "reporting_period_end": self.reporting_period_end.isoformat(),
            "authorized_date": self.financial_statements_authorized_date.isoformat(),
            "events": [e.to_dict() for e in self.events],
            "adjustment_events": [e.to_dict() for e in self.adjustment_events],
            "non_adjustment_events": [e.to_dict() for e in self.non_adjustment_events],
            "total_adjustment_impact": str(self.total_adjustment_impact()),
            "total_non_adjustment_impact": str(self.total_non_adjustment_impact()),
            "going_concern_assessment_revised": self.going_concern_assessment_revised,
            "going_concern_disclosure": self.going_concern_disclosure,
        }


@dataclass
class PSAK8ValidationResult:
    is_compliant: bool
    compliance_level: PSAK8ComplianceLevel
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
        if self.compliance_level != PSAK8ComplianceLevel.NON_COMPLIANT:
            self.compliance_level = PSAK8ComplianceLevel.NON_COMPLIANT

    def add_warning(self, warning: str) -> None:
        self.warnings.append(warning)
        if self.compliance_level == PSAK8ComplianceLevel.FULL:
            self.compliance_level = PSAK8ComplianceLevel.SUBSTANTIAL

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
class PSAK8EventClassifier:
    """Klasifikasi peristiwa menjadi adjusting atau non-adjusting."""

    @staticmethod
    def classify_event(description: str, event_date: date, reporting_end: date) -> EventType:
        """
        Mengklasifikasikan peristiwa berdasarkan PSAK 8.

        Adjusting events: memberikan bukti lebih lanjut tentang kondisi yang sudah ada
        pada akhir periode pelaporan.
        Non-adjusting events: menunjukkan kondisi yang baru timbul setelah periode.
        """
        # Peristiwa yang hampir selalu adjusting
        adjusting_keywords = [
            "penyelesaian kasus",
            "pemenang perkara",
            "putusan pengadilan",
            "kebangkrutan yang menunjukkan kondisi sudah ada",
            "fraud",
            "kesalahan",
            "penurunan nilai",
            "revaluasi setelah periode",
        ]
        # Peristiwa yang hampir selalu non-adjusting
        non_adjusting_keywords = [
            "dividen",
            "kombinasi bisnis",
            "akuisisi",
            "pembelian aset besar",
            "kerusakan aset",
            "kebakaran",
            "bencana alam",
            "fluktuasi kurs",
            "perubahan tarif pajak",
            "perubahan kebijakan",
        ]

        desc_lower = description.lower()
        for kw in adjusting_keywords:
            if kw in desc_lower:
                return EventType.ADJUSTING
        for kw in non_adjusting_keywords:
            if kw in desc_lower:
                return EventType.NON_ADJUSTING

        # Default: jika tanggal setelah periode, non-adjusting
        if event_date > reporting_end:
            return EventType.NON_ADJUSTING
        return EventType.ADJUSTING


class PSAK8EventService:
    """Layanan untuk menangani peristiwa setelah periode pelaporan."""

    @staticmethod
    def calculate_adjustment(original_amount: Decimal, new_amount: Decimal) -> Decimal:
        """Menghitung penyesuaian yang diperlukan."""
        return new_amount - original_amount

    @staticmethod
    def determine_disclosure_requirement(event: AfterReportingPeriodEvent) -> bool:
        """Menentukan apakah peristiwa perlu diungkapkan."""
        # Peristiwa non-adjusting material wajib diungkapkan
        if event.event_type == EventType.NON_ADJUSTING and event.financial_impact > Decimal(
            "10000000"
        ):
            return True
        # Peristiwa adjusting material wajib disesuaikan dan diungkapkan
        if event.event_type == EventType.ADJUSTING and event.financial_impact > Decimal("5000000"):
            return True
        # Peristiwa yang tidak material bisa tidak diungkapkan
        return event.financial_impact > Decimal("1000000")


# ============================================================================
# Rules
# ============================================================================
class PSAK8Rules:
    """Aturan PSAK 8."""

    @staticmethod
    def validate_authorization_date(
        disclosure: AfterReportingPeriodDisclosure,
    ) -> PSAK8ValidationResult:
        result = PSAK8ValidationResult(
            is_compliant=True, compliance_level=PSAK8ComplianceLevel.FULL
        )
        if disclosure.financial_statements_authorized_date < disclosure.reporting_period_end:
            result.add_error(
                "Tanggal otorisasi laporan keuangan tidak boleh sebelum akhir periode pelaporan"
            )
        if (
            disclosure.financial_statements_authorized_date - disclosure.reporting_period_end
        ).days > 180:
            result.add_warning("Jeda antara akhir periode dan otorisasi lebih dari 6 bulan")
        return result

    @staticmethod
    def validate_event_classification(
        events: list[AfterReportingPeriodEvent],
    ) -> PSAK8ValidationResult:
        result = PSAK8ValidationResult(
            is_compliant=True, compliance_level=PSAK8ComplianceLevel.FULL
        )
        for e in events:
            # Untuk peristiwa yang seharusnya adjusting tapi diklasifikasikan non-adjusting
            if e.event_type == EventType.NON_ADJUSTING and e.category in [
                EventCategory.SETTLEMENT_OF_COURT_CASE,
                EventCategory.FRAUD_OR_ERRORS,
                EventCategory.GOING_CONCERN_ISSUES,
            ]:
                result.add_error(
                    f"Peristiwa {e.event_description} seharusnya diklasifikasikan sebagai penyesuaian (adjusting event)"
                )
        return result

    @staticmethod
    def validate_adjustment_recording(
        adjustment_events: list[AfterReportingPeriodEvent],
    ) -> PSAK8ValidationResult:
        result = PSAK8ValidationResult(
            is_compliant=True, compliance_level=PSAK8ComplianceLevel.FULL
        )
        for e in adjustment_events:
            if e.financial_impact != 0 and not e.adjustment_journal_reference:
                result.add_error(
                    f"Peristiwa penyesuaian {e.event_description} dengan dampak {e.financial_impact} tidak memiliki referensi jurnal"
                )
        return result

    @staticmethod
    def validate_going_concern(disclosure: AfterReportingPeriodDisclosure) -> PSAK8ValidationResult:
        result = PSAK8ValidationResult(
            is_compliant=True, compliance_level=PSAK8ComplianceLevel.FULL
        )
        if disclosure.going_concern_assessment_revised and not disclosure.going_concern_disclosure:
            result.add_error("Revisi asumsi going concern tidak diungkapkan")
        return result


# ============================================================================
# Validator
# ============================================================================
class PSAK8Validator:
    def __init__(self):
        self._rules = PSAK8Rules()
        self._classifier = PSAK8EventClassifier()
        self._service = PSAK8EventService()

    def create_event(
        self,
        description: str,
        event_date: date,
        category: EventCategory,
        financial_impact: Decimal = Decimal(0),
        currency: str = "IDR",
        notes: str = "",
        event_type: EventType | None = None,
        reporting_end: date | None = None,
    ) -> AfterReportingPeriodEvent:
        """Membuat peristiwa, dengan klasifikasi otomatis jika event_type tidak ditentukan."""
        if event_type is None and reporting_end:
            event_type = self._classifier.classify_event(description, event_date, reporting_end)
        elif event_type is None:
            event_type = EventType.NON_ADJUSTING
        return AfterReportingPeriodEvent(
            event_id=uuid4(),
            event_description=description,
            event_date=event_date,
            event_type=event_type,
            category=category,
            financial_impact=financial_impact,
            currency=currency.upper(),
            notes=notes,
        )

    def create_disclosure(
        self,
        entity_id: UUID,
        entity_name: str,
        reporting_period_end: date,
        financial_statements_authorized_date: date,
    ) -> AfterReportingPeriodDisclosure:
        return AfterReportingPeriodDisclosure(
            disclosure_id=uuid4(),
            entity_id=entity_id,
            entity_name=entity_name,
            reporting_period_end=reporting_period_end,
            financial_statements_authorized_date=financial_statements_authorized_date,
        )

    def add_event(
        self, disclosure: AfterReportingPeriodDisclosure, event: AfterReportingPeriodEvent
    ) -> AfterReportingPeriodDisclosure:
        new_events = [*disclosure.events, event]
        return AfterReportingPeriodDisclosure(
            disclosure_id=disclosure.disclosure_id,
            entity_id=disclosure.entity_id,
            entity_name=disclosure.entity_name,
            reporting_period_end=disclosure.reporting_period_end,
            financial_statements_authorized_date=disclosure.financial_statements_authorized_date,
            events=new_events,
            going_concern_assessment_revised=disclosure.going_concern_assessment_revised,
            going_concern_disclosure=disclosure.going_concern_disclosure,
        )

    def set_going_concern(
        self, disclosure: AfterReportingPeriodDisclosure, revised: bool, disclosure_text: str = ""
    ) -> AfterReportingPeriodDisclosure:
        return AfterReportingPeriodDisclosure(
            disclosure_id=disclosure.disclosure_id,
            entity_id=disclosure.entity_id,
            entity_name=disclosure.entity_name,
            reporting_period_end=disclosure.reporting_period_end,
            financial_statements_authorized_date=disclosure.financial_statements_authorized_date,
            events=disclosure.events,
            going_concern_assessment_revised=revised,
            going_concern_disclosure=disclosure_text,
        )

    def update_adjustment_journal(
        self, disclosure: AfterReportingPeriodDisclosure, event_id: UUID, journal_ref: str
    ) -> AfterReportingPeriodDisclosure:
        new_events = []
        for e in disclosure.events:
            if e.event_id == event_id:
                e.adjustment_journal_reference = journal_ref
            new_events.append(e)
        return AfterReportingPeriodDisclosure(
            disclosure_id=disclosure.disclosure_id,
            entity_id=disclosure.entity_id,
            entity_name=disclosure.entity_name,
            reporting_period_end=disclosure.reporting_period_end,
            financial_statements_authorized_date=disclosure.financial_statements_authorized_date,
            events=new_events,
            going_concern_assessment_revised=disclosure.going_concern_assessment_revised,
            going_concern_disclosure=disclosure.going_concern_disclosure,
        )

    def validate_disclosure(
        self, disclosure: AfterReportingPeriodDisclosure
    ) -> PSAK8ValidationResult:
        result = self._rules.validate_authorization_date(disclosure)
        result = self._merge_results(
            result, self._rules.validate_event_classification(disclosure.events)
        )
        result = self._merge_results(
            result, self._rules.validate_adjustment_recording(disclosure.adjustment_events)
        )
        result = self._merge_results(result, self._rules.validate_going_concern(disclosure))
        return result

    def _merge_results(
        self, main: PSAK8ValidationResult, other: PSAK8ValidationResult
    ) -> PSAK8ValidationResult:
        main.errors.extend(other.errors)
        main.warnings.extend(other.warnings)
        main.is_compliant = main.is_compliant and other.is_compliant
        level_order = [
            PSAK8ComplianceLevel.FULL,
            PSAK8ComplianceLevel.SUBSTANTIAL,
            PSAK8ComplianceLevel.PARTIAL,
            PSAK8ComplianceLevel.NON_COMPLIANT,
        ]
        main_idx = level_order.index(main.compliance_level)
        other_idx = level_order.index(other.compliance_level)
        if other_idx > main_idx:
            main.compliance_level = level_order[other_idx]
        return main

    def get_requirements_summary(self) -> dict:
        return {
            "adjusting_events": [
                "Penyelesaian kasus pengadilan yang memberikan bukti kewajiban pada akhir periode",
                "Kebangkrutan pelanggan yang terjadi setelah periode, mengindikasikan kondisi sudah ada",
                "Penjualan persediaan yang menunjukkan NRV lebih rendah dari biaya",
                "Penemuan fraud atau kesalahan",
                "Penurunan nilai aset setelah periode yang mencerminkan kondisi pada akhir periode",
            ],
            "non_adjusting_events": [
                "Penurunan nilai pasar investasi setelah periode",
                "Deklarasi dividen",
                "Kombinasi bisnis besar",
                "Pembelian aset besar",
                "Kerusakan aset akibat kebakaran/bencana",
                "Perubahan tarif pajak atau kurs valuta asing",
            ],
            "disclosure_requirements": [
                "Sifat peristiwa",
                "Estimasi dampak keuangan (atau pernyataan tidak dapat diestimasi)",
                "Tanggal otorisasi laporan keuangan",
                "Untuk non-adjusting material, harus diungkapkan",
            ],
        }


# ============================================================================
# Singleton Accessor
# ============================================================================
_psak8_validator_instance: PSAK8Validator | None = None


def get_psak8_validator() -> PSAK8Validator:
    global _psak8_validator_instance
    if _psak8_validator_instance is None:
        _psak8_validator_instance = PSAK8Validator()
    return _psak8_validator_instance


AdjustingEvent = AfterReportingPeriodEvent
NonAdjustingEvent = AfterReportingPeriodEvent

# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    validator = get_psak8_validator()
    entity_id = uuid4()
    reporting_end = date(2026, 12, 31)
    auth_date = date(2027, 2, 28)

    disclosure = validator.create_disclosure(
        entity_id=entity_id,
        entity_name="PT Contoh Abadi",
        reporting_period_end=reporting_end,
        financial_statements_authorized_date=auth_date,
    )

    # Adding events
    event1 = validator.create_event(
        description="Penyelesaian kasus hukum dengan pelanggan, pengadilan memutuskan perusahaan membayar ganti rugi",
        event_date=date(2027, 1, 15),
        category=EventCategory.SETTLEMENT_OF_COURT_CASE,
        financial_impact=Decimal("50000000"),
        reporting_end=reporting_end,
    )
    disclosure = validator.add_event(disclosure, event1)
    disclosure = validator.update_adjustment_journal(disclosure, event1.event_id, "JRN-ADJ-001")

    event2 = validator.create_event(
        description="Deklarasi dividen tunai",
        event_date=date(2027, 2, 10),
        category=EventCategory.DECLARATION_OF_DIVIDEND,
        financial_impact=Decimal("200000000"),
        reporting_end=reporting_end,
    )
    disclosure = validator.add_event(disclosure, event2)

    event3 = validator.create_event(
        description="Kebakaran di gudang utama",
        event_date=date(2027, 1, 20),
        category=EventCategory.DESTRUCTION_OF_ASSETS,
        financial_impact=Decimal("500000000"),
        reporting_end=reporting_end,
    )
    disclosure = validator.add_event(disclosure, event3)

    # Validate
    result = validator.validate_disclosure(disclosure)
    print("Validation Result:")
    print(json.dumps(result.to_dict(), indent=2))
    print("\nDisclosure:")
    print(json.dumps(disclosure.to_dict(), indent=2, default=str))
