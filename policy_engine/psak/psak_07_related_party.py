#!/usr/bin/env python3
"""
Module: psak_07_related_party.py
Layer: 7 - Policy Engine & Standards / PSAK

Responsibility:
    PSAK 7: Pengungkapan Pihak Berelasi (setara dengan IAS 24).
    Mengatur identifikasi pihak-pihak yang memiliki hubungan istimewa dengan entitas
    pelapor, pengungkapan transaksi dan saldo dengan pihak berelasi, serta
    kompensasi manajemen kunci. Tujuannya untuk memastikan laporan keuangan
    mengungkapkan potensi dampak hubungan istimewa terhadap posisi keuangan
    dan kinerja entitas.

Dependencies:
    - datetime, decimal, enum, typing, dataclasses, uuid, hashlib, logging

Audit:
    Setiap identifikasi pihak berelasi dan transaksi dicatat dengan hash.
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
class RelationshipType(Enum):
    PARENT = "induk"
    SUBSIDIARY = "anak_perusahaan"
    ASSOCIATE = "asosiasi"
    JOINT_VENTURE = "ventura_bersama"
    KEY_MANAGEMENT = "manajemen_kunci"
    CLOSE_FAMILY = "keluarga_dekat"
    OTHER = "lainnya"


class TransactionType(Enum):
    PURCHASE = "pembelian"
    SALE = "penjualan"
    LOAN = "pinjaman"
    GUARANTEE = "jaminan"
    DIVIDEND = "dividen"
    SERVICE = "jasa"
    OTHER = "lainnya"


class CompensationType(Enum):
    SHORT_TERM_BENEFITS = "imbalan_jangka_pendek"
    POST_EMPLOYMENT_BENEFITS = "imbalan_pasca_kerja"
    TERMINATION_BENEFITS = "imbalan_pemutusan"
    SHARE_BASED_PAYMENT = "pembayaran_berbasis_saham"


class PSAK7ComplianceLevel(Enum):
    FULL = "penuh"
    SUBSTANTIAL = "substansial"
    PARTIAL = "sebagian"
    NON_COMPLIANT = "tidak_patuh"


# ============================================================================
# Exceptions
# ============================================================================
class PSAK7Error(Exception):
    pass


class RelatedPartyNotFoundError(PSAK7Error):
    pass


# ============================================================================
# Data Classes
# ============================================================================
@dataclass
class RelatedParty:
    """Pihak berelasi."""

    party_id: UUID
    party_name: str
    relationship_type: RelationshipType
    controlling_entity_id: UUID | None = None
    description: str = ""
    is_key_management: bool = False

    def to_dict(self) -> dict:
        return {
            "party_id": str(self.party_id),
            "party_name": self.party_name,
            "relationship_type": self.relationship_type.value,
            "controlling_entity": str(self.controlling_entity_id)
            if self.controlling_entity_id
            else None,
            "description": self.description,
            "is_key_management": self.is_key_management,
        }


@dataclass
class RelatedPartyTransaction:
    """Transaksi dengan pihak berelasi."""

    transaction_id: UUID
    party_id: UUID
    transaction_type: TransactionType
    amount: Decimal
    currency: str
    transaction_date: datetime
    terms_and_conditions: str = ""
    outstanding_balance: Decimal = Decimal(0)
    bad_debt_provision: Decimal = Decimal(0)
    is_arm_length: bool = True
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "transaction_id": str(self.transaction_id),
            "party_id": str(self.party_id),
            "transaction_type": self.transaction_type.value,
            "amount": str(self.amount),
            "currency": self.currency,
            "transaction_date": self.transaction_date.isoformat(),
            "terms_and_conditions": self.terms_and_conditions,
            "outstanding_balance": str(self.outstanding_balance),
            "bad_debt_provision": str(self.bad_debt_provision),
            "is_arm_length": self.is_arm_length,
            "description": self.description,
        }


@dataclass
class KeyManagementCompensation:
    """Kompensasi manajemen kunci."""

    compensation_id: UUID
    entity_id: UUID
    period_start: datetime
    period_end: datetime
    compensation_type: CompensationType
    amount: Decimal
    currency: str
    number_of_persons: int = 0
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "compensation_id": str(self.compensation_id),
            "entity_id": str(self.entity_id),
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "compensation_type": self.compensation_type.value,
            "amount": str(self.amount),
            "currency": self.currency,
            "number_of_persons": self.number_of_persons,
            "description": self.description,
        }


@dataclass
class RelatedPartyDisclosure:
    """Pengungkapan pihak berelasi secara keseluruhan."""

    disclosure_id: UUID
    entity_id: UUID
    entity_name: str
    reporting_period_end: datetime
    related_parties: list[RelatedParty] = field(default_factory=list)
    transactions: list[RelatedPartyTransaction] = field(default_factory=list)
    key_management_compensation: list[KeyManagementCompensation] = field(default_factory=list)
    control_relationship_disclosed: bool = False
    has_parent_entity: bool = False
    parent_entity_name: str | None = None
    ultimate_controlling_party: str | None = None

    def total_transactions_by_type(self, transaction_type: TransactionType) -> Decimal:
        # FIX: tambahkan Decimal(0) sebagai nilai awal sum
        return sum((t.amount for t in self.transactions if t.transaction_type == transaction_type), Decimal(0))

    def total_key_management_compensation(self) -> Decimal:
        return sum((k.amount for k in self.key_management_compensation), Decimal(0))

    def has_transactions_with_party(self, party_id: UUID) -> bool:
        return any(t.party_id == party_id for t in self.transactions)

    def to_dict(self) -> dict:
        return {
            "disclosure_id": str(self.disclosure_id),
            "entity_id": str(self.entity_id),
            "entity_name": self.entity_name,
            "reporting_period_end": self.reporting_period_end.isoformat(),
            "related_parties": [p.to_dict() for p in self.related_parties],
            "transactions": [t.to_dict() for t in self.transactions],
            "key_management_compensation": [k.to_dict() for k in self.key_management_compensation],
            "control_relationship_disclosed": self.control_relationship_disclosed,
            "has_parent_entity": self.has_parent_entity,
            "parent_entity_name": self.parent_entity_name,
            "ultimate_controlling_party": self.ultimate_controlling_party,
            "total_transactions": str(sum((t.amount for t in self.transactions), Decimal(0))),
            "total_key_management_compensation": str(self.total_key_management_compensation()),
        }


@dataclass
class PSAK7ValidationResult:
    is_compliant: bool
    compliance_level: PSAK7ComplianceLevel
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
        if self.compliance_level != PSAK7ComplianceLevel.NON_COMPLIANT:
            self.compliance_level = PSAK7ComplianceLevel.NON_COMPLIANT

    def add_warning(self, warning: str) -> None:
        self.warnings.append(warning)
        if self.compliance_level == PSAK7ComplianceLevel.FULL:
            self.compliance_level = PSAK7ComplianceLevel.SUBSTANTIAL

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
class PSAK7RelatedPartyService:
    """Service untuk identifikasi dan pengungkapan pihak berelasi."""

    @staticmethod
    def is_related_party(relationship: RelationshipType) -> bool:
        """Semua jenis relasi dianggap sebagai pihak berelasi."""
        return True

    @staticmethod
    def identify_related_parties(
        parent_id: UUID | None,
        subsidiaries: list[UUID],
        associates: list[UUID],
        key_management_ids: list[UUID],
        close_family_of_management: list[UUID],
    ) -> list[RelatedParty]:
        parties = []
        if parent_id:
            parties.append(
                RelatedParty(
                    party_id=parent_id,
                    party_name="Entitas Induk",
                    relationship_type=RelationshipType.PARENT,
                )
            )
        for sub in subsidiaries:
            parties.append(
                RelatedParty(
                    party_id=sub,
                    party_name=f"Anak Perusahaan {sub}",
                    relationship_type=RelationshipType.SUBSIDIARY,
                )
            )
        for assoc in associates:
            parties.append(
                RelatedParty(
                    party_id=assoc,
                    party_name=f"Asosiasi {assoc}",
                    relationship_type=RelationshipType.ASSOCIATE,
                )
            )
        for km in key_management_ids:
            parties.append(
                RelatedParty(
                    party_id=km,
                    party_name=f"Manajemen Kunci {km}",
                    relationship_type=RelationshipType.KEY_MANAGEMENT,
                    is_key_management=True,
                )
            )
        for cf in close_family_of_management:
            parties.append(
                RelatedParty(
                    party_id=cf,
                    party_name=f"Keluarga {cf}",
                    relationship_type=RelationshipType.CLOSE_FAMILY,
                )
            )
        return parties

    @staticmethod
    def requires_disclosure(transaction: RelatedPartyTransaction) -> bool:
        """Semua transaksi dengan pihak berelasi harus diungkapkan, kecuali yang tidak material."""
        # Contoh threshold materialitas sederhana
        return transaction.amount >= Decimal("1000000")


# ============================================================================
# Rules
# ============================================================================
class PSAK7Rules:
    """Aturan PSAK 7."""

    @staticmethod
    def validate_control_relationship(disclosure: RelatedPartyDisclosure) -> PSAK7ValidationResult:
        result = PSAK7ValidationResult(
            is_compliant=True, compliance_level=PSAK7ComplianceLevel.FULL
        )
        if not disclosure.control_relationship_disclosed:
            result.add_error(
                "Hubungan pengendali (entitas induk dan ultimate controlling party) tidak diungkapkan"
            )
        if disclosure.has_parent_entity and not disclosure.parent_entity_name:
            result.add_error("Nama entitas induk tidak diungkapkan")
        return result

    @staticmethod
    def validate_transaction_disclosure(
        transactions: list[RelatedPartyTransaction],
    ) -> PSAK7ValidationResult:
        result = PSAK7ValidationResult(
            is_compliant=True, compliance_level=PSAK7ComplianceLevel.FULL
        )
        for tx in transactions:
            if not tx.terms_and_conditions:
                result.add_warning(
                    f"Transaksi dengan pihak berelasi {tx.party_id} tidak mengungkapkan syarat dan ketentuan"
                )
            if tx.outstanding_balance != 0 and not tx.is_arm_length:
                result.add_warning(
                    f"Saldo outstanding dengan pihak berelasi {tx.party_id} tidak berdasarkan harga pasar wajar"
                )
        return result

    @staticmethod
    def validate_key_management_compensation(
        compensations: list[KeyManagementCompensation],
    ) -> PSAK7ValidationResult:
        result = PSAK7ValidationResult(
            is_compliant=True, compliance_level=PSAK7ComplianceLevel.FULL
        )
        total = sum((c.amount for c in compensations), Decimal(0))
        if total == 0 and compensations:
            result.add_error("Kompensasi manajemen kunci tidak diungkapkan atau nilai nol")
        if len(compensations) < 4:
            result.add_warning(
                "Kompensasi manajemen kunci tidak mencakup semua jenis imbalan (jangka pendek, pasca kerja, pemutusan, berbasis saham)"
            )
        return result


# ============================================================================
# Validator
# ============================================================================
class PSAK7Validator:
    def __init__(self):
        self._rules = PSAK7Rules()
        self._service = PSAK7RelatedPartyService()

    def create_related_party(
        self,
        party_name: str,
        relationship_type: RelationshipType,
        controlling_entity_id: UUID | None = None,
        description: str = "",
        is_key_management: bool = False,
    ) -> RelatedParty:
        return RelatedParty(
            party_id=uuid4(),
            party_name=party_name,
            relationship_type=relationship_type,
            controlling_entity_id=controlling_entity_id,
            description=description,
            is_key_management=is_key_management,
        )

    def create_transaction(
        self,
        party_id: UUID,
        transaction_type: TransactionType,
        amount: Decimal,
        currency: str,
        transaction_date: datetime,
        terms_and_conditions: str = "",
        outstanding_balance: Decimal = Decimal(0),
        is_arm_length: bool = True,
        description: str = "",
    ) -> RelatedPartyTransaction:
        return RelatedPartyTransaction(
            transaction_id=uuid4(),
            party_id=party_id,
            transaction_type=transaction_type,
            amount=amount,
            currency=currency.upper(),
            transaction_date=transaction_date,
            terms_and_conditions=terms_and_conditions,
            outstanding_balance=outstanding_balance,
            is_arm_length=is_arm_length,
            description=description,
        )

    def create_compensation(
        self,
        entity_id: UUID,
        period_start: datetime,
        period_end: datetime,
        compensation_type: CompensationType,
        amount: Decimal,
        currency: str,
        number_of_persons: int = 0,
        description: str = "",
    ) -> KeyManagementCompensation:
        return KeyManagementCompensation(
            compensation_id=uuid4(),
            entity_id=entity_id,
            period_start=period_start,
            period_end=period_end,
            compensation_type=compensation_type,
            amount=amount,
            currency=currency.upper(),
            number_of_persons=number_of_persons,
            description=description,
        )

    def create_disclosure(
        self,
        entity_id: UUID,
        entity_name: str,
        reporting_period_end: datetime,
        control_relationship_disclosed: bool = False,
        has_parent_entity: bool = False,
        parent_entity_name: str | None = None,
        ultimate_controlling_party: str | None = None,
    ) -> RelatedPartyDisclosure:
        return RelatedPartyDisclosure(
            disclosure_id=uuid4(),
            entity_id=entity_id,
            entity_name=entity_name,
            reporting_period_end=reporting_period_end,
            control_relationship_disclosed=control_relationship_disclosed,
            has_parent_entity=has_parent_entity,
            parent_entity_name=parent_entity_name,
            ultimate_controlling_party=ultimate_controlling_party,
        )

    def add_related_party(
        self, disclosure: RelatedPartyDisclosure, party: RelatedParty
    ) -> RelatedPartyDisclosure:
        new_parties = [*disclosure.related_parties, party]
        return RelatedPartyDisclosure(
            disclosure_id=disclosure.disclosure_id,
            entity_id=disclosure.entity_id,
            entity_name=disclosure.entity_name,
            reporting_period_end=disclosure.reporting_period_end,
            related_parties=new_parties,
            transactions=disclosure.transactions,
            key_management_compensation=disclosure.key_management_compensation,
            control_relationship_disclosed=disclosure.control_relationship_disclosed,
            has_parent_entity=disclosure.has_parent_entity,
            parent_entity_name=disclosure.parent_entity_name,
            ultimate_controlling_party=disclosure.ultimate_controlling_party,
        )

    def add_transaction(
        self, disclosure: RelatedPartyDisclosure, transaction: RelatedPartyTransaction
    ) -> RelatedPartyDisclosure:
        new_transactions = [*disclosure.transactions, transaction]
        return RelatedPartyDisclosure(
            disclosure_id=disclosure.disclosure_id,
            entity_id=disclosure.entity_id,
            entity_name=disclosure.entity_name,
            reporting_period_end=disclosure.reporting_period_end,
            related_parties=disclosure.related_parties,
            transactions=new_transactions,
            key_management_compensation=disclosure.key_management_compensation,
            control_relationship_disclosed=disclosure.control_relationship_disclosed,
            has_parent_entity=disclosure.has_parent_entity,
            parent_entity_name=disclosure.parent_entity_name,
            ultimate_controlling_party=disclosure.ultimate_controlling_party,
        )

    def add_compensation(
        self, disclosure: RelatedPartyDisclosure, compensation: KeyManagementCompensation
    ) -> RelatedPartyDisclosure:
        new_comp = [*disclosure.key_management_compensation, compensation]
        return RelatedPartyDisclosure(
            disclosure_id=disclosure.disclosure_id,
            entity_id=disclosure.entity_id,
            entity_name=disclosure.entity_name,
            reporting_period_end=disclosure.reporting_period_end,
            related_parties=disclosure.related_parties,
            transactions=disclosure.transactions,
            key_management_compensation=new_comp,
            control_relationship_disclosed=disclosure.control_relationship_disclosed,
            has_parent_entity=disclosure.has_parent_entity,
            parent_entity_name=disclosure.parent_entity_name,
            ultimate_controlling_party=disclosure.ultimate_controlling_party,
        )

    def validate_disclosure(self, disclosure: RelatedPartyDisclosure) -> PSAK7ValidationResult:
        result = self._rules.validate_control_relationship(disclosure)
        result = self._merge_results(
            result, self._rules.validate_transaction_disclosure(disclosure.transactions)
        )
        result = self._merge_results(
            result,
            self._rules.validate_key_management_compensation(
                disclosure.key_management_compensation
            ),
        )
        # Additional: check that all related parties have transactions disclosed (if any)
        for party in disclosure.related_parties:
            if not disclosure.has_transactions_with_party(party.party_id):
                result.add_warning(
                    f"Pihak berelasi {party.party_name} ({party.relationship_type.value}) tidak memiliki transaksi yang diungkapkan"
                )
        return result

    def _merge_results(
        self, main: PSAK7ValidationResult, other: PSAK7ValidationResult
    ) -> PSAK7ValidationResult:
        main.errors.extend(other.errors)
        main.warnings.extend(other.warnings)
        main.is_compliant = main.is_compliant and other.is_compliant
        level_order = [
            PSAK7ComplianceLevel.FULL,
            PSAK7ComplianceLevel.SUBSTANTIAL,
            PSAK7ComplianceLevel.PARTIAL,
            PSAK7ComplianceLevel.NON_COMPLIANT,
        ]
        main_idx = level_order.index(main.compliance_level)
        other_idx = level_order.index(other.compliance_level)
        if other_idx > main_idx:
            main.compliance_level = level_order[other_idx]
        return main

    def get_requirements_summary(self) -> dict:
        return {
            "related_parties": [
                "Entitas induk",
                "Anak perusahaan",
                "Asosiasi",
                "Ventura bersama",
                "Manajemen kunci dan keluarga dekatnya",
                "Entitas yang dikendalikan oleh manajemen kunci",
            ],
            "disclosure_requirements": [
                "Nama hubungan pengendali",
                "Jenis transaksi",
                "Jumlah transaksi dan saldo outstanding",
                "Syarat dan ketentuan (termasuk apakah harga pasar wajar)",
                "Jaminan yang diberikan/diterima",
                "Kompensasi manajemen kunci",
            ],
            "exemptions": [
                "Transaksi yang tidak material (dapat diabaikan)",
                "Laporan keuangan entitas induk saja (tidak konsolidasi) tidak perlu mengungkapkan transaksi dengan anak perusahaan",
            ],
        }


# ============================================================================
# Singleton Accessor
# ============================================================================
_psak7_validator_instance: PSAK7Validator | None = None


def get_psak7_validator() -> PSAK7Validator:
    global _psak7_validator_instance
    if _psak7_validator_instance is None:
        _psak7_validator_instance = PSAK7Validator()
    return _psak7_validator_instance


RelatedPartyRelationship = RelatedParty
RelatedPartyType = RelationshipType

# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    validator = get_psak7_validator()
    entity_id = uuid4()

    # Create disclosure
    disclosure = validator.create_disclosure(
        entity_id=entity_id,
        entity_name="PT Induk Sejahtera",
        reporting_period_end=datetime(2026, 12, 31, tzinfo=UTC),
        control_relationship_disclosed=True,
        has_parent_entity=False,
        ultimate_controlling_party="Mr. Budi (pemilik tunggal)",
    )

    # Add related parties
    parent = validator.create_related_party("PT Anak Maju", RelationshipType.SUBSIDIARY)
    disclosure = validator.add_related_party(disclosure, parent)
    associate = validator.create_related_party("PT Rekan Kerja", RelationshipType.ASSOCIATE)
    disclosure = validator.add_related_party(disclosure, associate)

    # Add transactions
    tx1 = validator.create_transaction(
        party_id=parent.party_id,
        transaction_type=TransactionType.PURCHASE,
        amount=Decimal("500000000"),
        currency="IDR",
        transaction_date=datetime(2026, 6, 15, tzinfo=UTC),
        terms_and_conditions="Pembelian bahan baku, harga normal, pembayaran 30 hari",
        outstanding_balance=Decimal("100000000"),
        is_arm_length=True,
    )
    disclosure = validator.add_transaction(disclosure, tx1)

    tx2 = validator.create_transaction(
        party_id=associate.party_id,
        transaction_type=TransactionType.SERVICE,
        amount=Decimal("100000000"),
        currency="IDR",
        transaction_date=datetime(2026, 9, 1, tzinfo=UTC),
        terms_and_conditions="Jasa konsultasi",
        outstanding_balance=Decimal("0"),
        is_arm_length=True,
    )
    disclosure = validator.add_transaction(disclosure, tx2)

    # Add key management compensation
    comp1 = validator.create_compensation(
        entity_id=entity_id,
        period_start=datetime(2026, 1, 1, tzinfo=UTC),
        period_end=datetime(2026, 12, 31, tzinfo=UTC),
        compensation_type=CompensationType.SHORT_TERM_BENEFITS,
        amount=Decimal("500000000"),
        currency="IDR",
        number_of_persons=5,
    )
    disclosure = validator.add_compensation(disclosure, comp1)

    comp2 = validator.create_compensation(
        entity_id=entity_id,
        period_start=datetime(2026, 1, 1, tzinfo=UTC),
        period_end=datetime(2026, 12, 31, tzinfo=UTC),
        compensation_type=CompensationType.SHARE_BASED_PAYMENT,
        amount=Decimal("100000000"),
        currency="IDR",
        number_of_persons=3,
    )
    disclosure = validator.add_compensation(disclosure, comp2)

    # Validate
    result = validator.validate_disclosure(disclosure)
    print("Validation Result:")
    print(json.dumps(result.to_dict(), indent=2))
    print("\nDisclosure:")
    print(json.dumps(disclosure.to_dict(), indent=2, default=str))
