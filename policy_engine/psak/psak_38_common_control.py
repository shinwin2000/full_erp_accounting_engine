#!/usr/bin/env python3
"""
Module: psak_38_common_control.py
Layer: 7 - Policy Engine & Standards / PSAK

Responsibility:
    PSAK 38: Entitas Sepengendali (transaksi antar entitas sepengendali).
    Mengatur akuntansi untuk kombinasi bisnis, transfer aset, atau pertukaran
    ekuitas antara entitas yang berada di bawah pengendalian yang sama
    (entitas induk yang sama). Tidak menggunakan metode akuisisi (seperti PSAK 22),
    tetapi menggunakan metode nilai buku (book value method) atau pooling of interests,
    karena transaksi tersebut tidak mencerminkan pertukaran yang wajar di pasar.
    Mencakup merger, spin-off, transfer aset neto, dan pembentukan entitas baru.

Dependencies:
    - datetime, decimal, enum, typing, dataclasses, uuid, hashlib, logging

Audit:
    Setiap transaksi sepengendali, penentuan nilai buku, dan pengungkapan dicatat.
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
class PSAK38TransactionType(Enum):
    MERGER = "penggabungan"  # Merger entitas sepengendali
    ACQUISITION = "akuisisi"  # Akuisisi entitas sepengendali
    TRANSFER_OF_ASSETS = "transfer_aset"
    TRANSFER_OF_EQUITY = "transfer_ekuitas"
    SPIN_OFF = "pemisahan"
    NEW_ENTITY_FORMATION = "pembentukan_entitas_baru"


class PSAK38AccountingMethod(Enum):
    BOOK_VALUE_METHOD = "nilai_buku"  # Metode nilai buku (pooling of interests)
    PREDECESSOR_METHOD = "pendahulu"  # Metode predecessor (nilai buku dari entitas tertinggi)


class PSAK38ComplianceLevel(Enum):
    FULL = "penuh"
    SUBSTANTIAL = "substansial"
    PARTIAL = "sebagian"
    NON_COMPLIANT = "tidak_patuh"


# ============================================================================
# Exceptions
# ============================================================================
class PSAK38Error(Exception):
    pass


class NoCommonControlError(PSAK38Error):
    pass


# ============================================================================
# Data Classes
# ============================================================================
@dataclass
class PSAK38Entity:
    """Entitas yang terlibat dalam transaksi sepengendali."""

    entity_id: UUID
    entity_name: str
    ultimate_parent_id: UUID
    ultimate_parent_name: str
    book_value_equity: Decimal  # Nilai buku ekuitas pada tanggal transaksi
    assets: dict[str, Decimal] = field(default_factory=dict)
    liabilities: dict[str, Decimal] = field(default_factory=dict)
    net_assets: Decimal = Decimal(0)

    def __post_init__(self):
        self.net_assets = sum(self.assets.values()) - sum(self.liabilities.values())

    def to_dict(self) -> dict:
        return {
            "entity_id": str(self.entity_id),
            "entity_name": self.entity_name,
            "ultimate_parent": self.ultimate_parent_name,
            "book_value_equity": str(self.book_value_equity),
            "net_assets": str(self.net_assets),
        }


@dataclass
class PSAK38Transaction:
    """Transaksi sepengendali."""

    transaction_id: UUID
    transaction_type: PSAK38TransactionType
    transaction_date: datetime
    accounting_method: PSAK38AccountingMethod
    transferor_entity: PSAK38Entity
    transferee_entity: PSAK38Entity
    consideration_transferred: Decimal = Decimal(0)  # Nilai imbalan yang dialihkan (jika ada)
    difference_to_equity: Decimal = Decimal(
        0
    )  # Selisih yang diakui sebagai penambah/pengurang ekuitas
    notes: str = ""

    @property
    def net_assets_transferred(self) -> Decimal:
        return self.transferor_entity.net_assets

    def calculate_difference(self) -> Decimal:
        return self.consideration_transferred - self.net_assets_transferred

    def to_dict(self) -> dict:
        return {
            "transaction_id": str(self.transaction_id),
            "type": self.transaction_type.value,
            "date": self.transaction_date.isoformat(),
            "method": self.accounting_method.value,
            "transferor": self.transferor_entity.to_dict(),
            "transferee": self.transferee_entity.to_dict(),
            "consideration": str(self.consideration_transferred),
            "net_assets_transferred": str(self.net_assets_transferred),
            "difference_to_equity": str(self.difference_to_equity),
            "notes": self.notes,
        }


@dataclass
class PSAK38CommonControlRegister:
    """Register transaksi sepengendali."""

    register_id: UUID
    entity_id: UUID
    entity_name: str
    transactions: list[PSAK38Transaction] = field(default_factory=list)

    def total_effect_on_equity(self) -> Decimal:
        return sum(t.difference_to_equity for t in self.transactions)

    def to_dict(self) -> dict:
        return {
            "register_id": str(self.register_id),
            "entity_id": str(self.entity_id),
            "entity_name": self.entity_name,
            "total_equity_effect": str(self.total_effect_on_equity()),
            "transactions": [t.to_dict() for t in self.transactions],
        }


@dataclass
class PSAK38ValidationResult:
    is_compliant: bool
    compliance_level: PSAK38ComplianceLevel
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
        if self.compliance_level != PSAK38ComplianceLevel.NON_COMPLIANT:
            self.compliance_level = PSAK38ComplianceLevel.NON_COMPLIANT

    def add_warning(self, warning: str) -> None:
        self.warnings.append(warning)
        if self.compliance_level == PSAK38ComplianceLevel.FULL:
            self.compliance_level = PSAK38ComplianceLevel.SUBSTANTIAL

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
class PSAK38CommonControlService:
    """Service untuk transaksi sepengendali."""

    @staticmethod
    def is_common_control(
        entity_a: PSAK38Entity,
        entity_b: PSAK38Entity,
    ) -> bool:
        """Memeriksa apakah dua entitas berada di bawah pengendalian yang sama."""
        return entity_a.ultimate_parent_id == entity_b.ultimate_parent_id

    @staticmethod
    def determine_accounting_method(
        transaction_type: PSAK38TransactionType,
        is_merger: bool,
    ) -> PSAK38AccountingMethod:
        """Menentukan metode akuntansi yang sesuai (biasanya nilai buku)."""
        if is_merger or transaction_type in [
            PSAK38TransactionType.MERGER,
            PSAK38TransactionType.NEW_ENTITY_FORMATION,
        ]:
            return PSAK38AccountingMethod.BOOK_VALUE_METHOD
        return PSAK38AccountingMethod.PREDECESSOR_METHOD

    @staticmethod
    def compute_book_value_net_assets(entity: PSAK38Entity) -> Decimal:
        """Nilai buku aset neto yang ditransfer."""
        return entity.net_assets

    @staticmethod
    def compute_equity_adjustment(consideration: Decimal, net_assets: Decimal) -> Decimal:
        """Selisih yang diakui langsung di ekuitas (tidak di laba rugi)."""
        return consideration - net_assets


# ============================================================================
# Rules
# ============================================================================
class PSAK38Rules:
    """Aturan PSAK 38."""

    @staticmethod
    def validate_common_control(
        entity_a: PSAK38Entity, entity_b: PSAK38Entity
    ) -> PSAK38ValidationResult:
        result = PSAK38ValidationResult(
            is_compliant=True, compliance_level=PSAK38ComplianceLevel.FULL
        )
        if entity_a.ultimate_parent_id != entity_b.ultimate_parent_id:
            result.add_error(
                "Entitas tidak berada di bawah pengendalian yang sama (common control)"
            )
        return result

    @staticmethod
    def validate_consideration(transaction: PSAK38Transaction) -> PSAK38ValidationResult:
        result = PSAK38ValidationResult(
            is_compliant=True, compliance_level=PSAK38ComplianceLevel.FULL
        )
        if transaction.consideration_transferred < 0:
            result.add_error("Imbalan yang dialihkan tidak boleh negatif")
        return result

    @staticmethod
    def validate_disclosure(transaction: PSAK38Transaction) -> PSAK38ValidationResult:
        result = PSAK38ValidationResult(
            is_compliant=True, compliance_level=PSAK38ComplianceLevel.FULL
        )
        if not transaction.notes:
            result.add_warning("Pengungkapan untuk transaksi sepengendali tidak lengkap")
        return result


# ============================================================================
# Validator
# ============================================================================
class PSAK38Validator:
    def __init__(self):
        self._rules = PSAK38Rules()
        self._service = PSAK38CommonControlService()

    def create_entity(
        self,
        entity_id: UUID,
        entity_name: str,
        ultimate_parent_id: UUID,
        ultimate_parent_name: str,
        book_value_equity: Decimal,
        assets: dict[str, Decimal] | None = None,
        liabilities: dict[str, Decimal] | None = None,
    ) -> PSAK38Entity:
        return PSAK38Entity(
            entity_id=entity_id,
            entity_name=entity_name,
            ultimate_parent_id=ultimate_parent_id,
            ultimate_parent_name=ultimate_parent_name,
            book_value_equity=book_value_equity,
            assets=assets or {},
            liabilities=liabilities or {},
        )

    def create_transaction(
        self,
        transaction_type: PSAK38TransactionType,
        transaction_date: datetime,
        transferor: PSAK38Entity,
        transferee: PSAK38Entity,
        consideration_transferred: Decimal = Decimal(0),
        accounting_method: PSAK38AccountingMethod | None = None,
        notes: str = "",
    ) -> PSAK38Transaction:
        if accounting_method is None:
            accounting_method = self._service.determine_accounting_method(
                transaction_type, is_merger=True
            )
        diff = self._service.compute_equity_adjustment(
            consideration_transferred, transferor.net_assets
        )
        return PSAK38Transaction(
            transaction_id=uuid4(),
            transaction_type=transaction_type,
            transaction_date=transaction_date,
            accounting_method=accounting_method,
            transferor_entity=transferor,
            transferee_entity=transferee,
            consideration_transferred=consideration_transferred,
            difference_to_equity=diff,
            notes=notes,
        )

    def create_register(
        self,
        entity_id: UUID,
        entity_name: str,
    ) -> PSAK38CommonControlRegister:
        return PSAK38CommonControlRegister(
            register_id=uuid4(),
            entity_id=entity_id,
            entity_name=entity_name,
        )

    def add_transaction(
        self, register: PSAK38CommonControlRegister, transaction: PSAK38Transaction
    ) -> PSAK38CommonControlRegister:
        new_transactions = [*register.transactions, transaction]
        return PSAK38CommonControlRegister(
            register_id=register.register_id,
            entity_id=register.entity_id,
            entity_name=register.entity_name,
            transactions=new_transactions,
        )

    def validate_common_control(self, transaction: PSAK38Transaction) -> PSAK38ValidationResult:
        result = self._rules.validate_common_control(
            transaction.transferor_entity,
            transaction.transferee_entity,
        )
        result = self._merge_results(result, self._rules.validate_consideration(transaction))
        result = self._merge_results(result, self._rules.validate_disclosure(transaction))
        return result

    def _merge_results(
        self, main: PSAK38ValidationResult, other: PSAK38ValidationResult
    ) -> PSAK38ValidationResult:
        main.errors.extend(other.errors)
        main.warnings.extend(other.warnings)
        main.is_compliant = main.is_compliant and other.is_compliant
        level_order = [
            PSAK38ComplianceLevel.FULL,
            PSAK38ComplianceLevel.SUBSTANTIAL,
            PSAK38ComplianceLevel.PARTIAL,
            PSAK38ComplianceLevel.NON_COMPLIANT,
        ]
        main_idx = level_order.index(main.compliance_level)
        other_idx = level_order.index(other.compliance_level)
        if other_idx > main_idx:
            main.compliance_level = level_order[other_idx]
        return main

    def get_requirements_summary(self) -> dict:
        return {
            "scope": "Transaksi antar entitas sepengendali (common control) - merger, akuisisi, transfer aset/ekuitas",
            "accounting_method": "Metode nilai buku (book value method / pooling of interests) - tidak mengakui goodwill",
            "measurement": "Aset dan liabilitas dicatat pada nilai buku di entitas transferor",
            "difference": "Selisih antara imbalan yang dialihkan dengan nilai buku aset neto diakui langsung di ekuitas",
            "disclosures": [
                "Nama entitas yang terlibat",
                "Sifat hubungan pengendali",
                "Metode akuntansi yang digunakan",
                "Jumlah selisih yang diakui di ekuitas",
            ],
        }


# ============================================================================
# Singleton Accessor
# ============================================================================
_psak38_validator_instance: PSAK38Validator | None = None


def get_psak38_validator() -> PSAK38Validator:
    global _psak38_validator_instance
    if _psak38_validator_instance is None:
        _psak38_validator_instance = PSAK38Validator()
    return _psak38_validator_instance


# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    validator = get_psak38_validator()
    parent_id = uuid4()
    parent_name = "PT Induk Sejahtera"

    # Entitas A (transferor) - nilai buku ekuitas 1M
    entity_a = validator.create_entity(
        entity_id=uuid4(),
        entity_name="PT Anak A",
        ultimate_parent_id=parent_id,
        ultimate_parent_name=parent_name,
        book_value_equity=Decimal("1000000000"),
        assets={"Kas": Decimal("500000000"), "Bangunan": Decimal("800000000")},
        liabilities={"Utang Bank": Decimal("300000000")},
    )

    # Entitas B (transferee)
    entity_b = validator.create_entity(
        entity_id=uuid4(),
        entity_name="PT Anak B",
        ultimate_parent_id=parent_id,
        ultimate_parent_name=parent_name,
        book_value_equity=Decimal("500000000"),
    )

    # Transaksi: transfer aset neto dari A ke B dengan imbalan saham (nilai buku)
    transaction = validator.create_transaction(
        transaction_type=PSAK38TransactionType.TRANSFER_OF_ASSETS,
        transaction_date=datetime(2026, 6, 30, tzinfo=UTC),
        transferor=entity_a,
        transferee=entity_b,
        consideration_transferred=Decimal("1000000000"),  # nilai buku ekuitas A
        notes="Transfer aset neto PT Anak A ke PT Anak B sebagai bagian restrukturisasi internal",
    )

    # Validasi common control
    result = validator.validate_common_control(transaction)
    print("Validation Result:")
    print(json.dumps(result.to_dict(), indent=2))
    print("\nTransaction Details:")
    print(json.dumps(transaction.to_dict(), indent=2, default=str))
    print(f"Selisih yang diakui di ekuitas: {transaction.difference_to_equity}")
# ============================================================================
# Compatibility alias for package-level aggregator (__init__.py)
# ============================================================================
CommonControlTransaction = PSAK38Transaction

# ============================================================================
# Compatibility alias for transaction type mapping
# ============================================================================
CommonControlTransactionType = PSAK38TransactionType
