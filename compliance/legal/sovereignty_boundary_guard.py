#!/usr/bin/env python3
"""
Module: sovereignty_boundary_guard.py
Layer: Compliance / Legal

Responsibility:
    Menegakkan batas kedaulatan data: memastikan data residensi sesuai dengan yurisdiksi,
    dan mencegah transfer data lintas batas yang tidak sah (sesuai dengan UU PDP Indonesia,
    GDPR Eropa, dan regulasi serupa). Mendukung validasi data residency, user access
    lintas yurisdiksi, data classification (public, internal, confidential, restricted),
    dan audit trail.

Dependencies:
    - datetime, enum, typing, hashlib, json, logging

Audit:
    Setiap pelanggaran batas kedaulatan (atau percobaan) dicatat dengan hash.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from enum import Enum
from typing import ClassVar
from uuid import UUID, uuid4

from .jurisdiction_definition import JurisdictionDefinition
from .legal_exceptions import SovereigntyViolationError

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================
class DataClassification(Enum):
    PUBLIC = "public"  # Dapat diproses di mana saja
    INTERNAL = "internal"  # Hanya di dalam yurisdiksi asal
    CONFIDENTIAL = "confidential"  # Hanya di dalam yurisdiksi asal + perlindungan tambahan
    RESTRICTED = "restricted"  # Tidak boleh keluar dari yurisdiksi asal
    PERSONAL = "personal"  # Data pribadi (UU PDP, GDPR)


class TransferBasis(Enum):
    CONSENT = "consent"  # Persetujuan subjek data
    CONTRACT = "contract"  # Diperlukan untuk kontrak
    LEGAL_OBLIGATION = "legal_obligation"  # Kewajiban hukum
    PUBLIC_INTEREST = "public_interest"  # Kepentingan publik
    LEGITIMATE_INTEREST = "legitimate_interest"  # Kepentingan sah
    ADEQUACY_DECISION = "adequacy_decision"  # Negara tujuan memiliki tingkat perlindungan memadai
    SCC = "standard_contractual_clauses"  # Standard Contractual Clauses
    BCR = "binding_corporate_rules"  # Binding Corporate Rules


# ============================================================================
# Data Classes
# ============================================================================
class TransferRecord:
    """Rekaman transfer data lintas batas."""

    def __init__(
        self,
        transfer_id: UUID,
        data_type: DataClassification,
        source_jurisdiction: str,
        target_jurisdiction: str,
        transfer_basis: TransferBasis,
        amount_of_records: int | None = None,
        approved_by: UUID | None = None,
        justification: str = "",
        timestamp: datetime | None = None,
    ):
        self.id = transfer_id
        self.data_type = data_type
        self.source_jurisdiction = source_jurisdiction
        self.target_jurisdiction = target_jurisdiction
        self.transfer_basis = transfer_basis
        self.amount_of_records = amount_of_records
        self.approved_by = approved_by
        self.justification = justification
        self.timestamp = timestamp or datetime.utcnow()
        self._hash = self._compute_hash()

    def _compute_hash(self) -> str:
        data = {
            "transfer_id": str(self.id),
            "source": self.source_jurisdiction,
            "target": self.target_jurisdiction,
            "basis": self.transfer_basis.value,
            "timestamp": self.timestamp.isoformat(),
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    def to_dict(self) -> dict:
        return {
            "transfer_id": str(self.id),
            "data_type": self.data_type.value,
            "source_jurisdiction": self.source_jurisdiction,
            "target_jurisdiction": self.target_jurisdiction,
            "transfer_basis": self.transfer_basis.value,
            "amount_of_records": self.amount_of_records,
            "approved_by": str(self.approved_by) if self.approved_by else None,
            "justification": self.justification,
            "timestamp": self.timestamp.isoformat(),
            "hash": self._hash,
        }


# ============================================================================
# SovereigntyBoundaryGuard Core
# ============================================================================
class SovereigntyBoundaryGuard:
    """
    Penegak batas kedaulatan data untuk kepatuhan lintas yurisdiksi.
    """

    # Daftar yurisdiksi yang memiliki tingkat perlindungan data memadai (adequacy decision) untuk Indonesia
    ADEQUATE_JURISDICTIONS_FOR_ID: ClassVar[set[str]] = {
        "SG", "JP", "KR", "AU", "NZ", "CH", "GB", "US"
    }

    # Daftar transfer yang dilarang (default blacklist)
    RESTRICTED_TRANSFERS: ClassVar[dict[tuple[str, str], str]] = {
        ("ID", "CN"): "Data transfer to China is restricted without specific approval",
        ("ID", "RU"): "Data transfer to Russia is restricted due to sanctions",
        ("ID", "XX"): "Unknown jurisdiction - transfer not allowed",
    }

    def __init__(self):
        self._jurisdiction_def = JurisdictionDefinition()
        self._transfers: list[TransferRecord] = []
        self._allowed_cross_border_roles = {
            "global_administrator",
            "legal_compliance_officer",
            "data_protection_officer",
        }

    def check_data_residency(
        self,
        data_source_jurisdiction: str,
        data_processing_jurisdiction: str,
        data_classification: DataClassification = DataClassification.PERSONAL,
    ) -> tuple[bool, list[str]]:
        """
        Memeriksa apakah data dari source jurisdiction dapat diproses di processing jurisdiction.
        Returns (allowed, list_of_violations).
        """
        violations = []
        if data_source_jurisdiction == data_processing_jurisdiction:
            return True, []

        # 1. Cek aturan khusus (blacklist)
        restriction_key = (data_source_jurisdiction, data_processing_jurisdiction)
        if restriction_key in self.RESTRICTED_TRANSFERS:
            violations.append(self.RESTRICTED_TRANSFERS[restriction_key])

        # 2. Data restricted tidak boleh keluar dari yurisdiksi asal
        if data_classification == DataClassification.RESTRICTED:
            violations.append(f"Restricted data cannot leave {data_source_jurisdiction}")

        # 3. Data personal (GDPR/UU PDP) memerlukan basis transfer yang valid
        if (
            data_classification == DataClassification.PERSONAL
            and data_processing_jurisdiction not in self.ADEQUATE_JURISDICTIONS_FOR_ID
        ):
            violations.append(
                f"Personal data transfer to {data_processing_jurisdiction} requires adequacy decision or SCCs"
            )

        # 4. Data confidential hanya boleh ke yurisdiksi dengan tingkat perlindungan memadai
        if (
            data_classification == DataClassification.CONFIDENTIAL
            and data_processing_jurisdiction not in self.ADEQUATE_JURISDICTIONS_FOR_ID
            and data_processing_jurisdiction != data_source_jurisdiction
        ):
            violations.append(
                f"Confidential data transfer to {data_processing_jurisdiction} not allowed"
            )

        return len(violations) == 0, violations

    def check_user_access(
        self,
        user_jurisdiction: str,
        resource_jurisdiction: str,
        user_role: str,
        data_classification: DataClassification = DataClassification.INTERNAL,
    ) -> tuple[bool, list[str]]:
        """
        Memeriksa apakah user dari yurisdiksi tertentu dapat mengakses resource di yurisdiksi lain.
        Returns (allowed, list_of_violations).
        """
        if user_jurisdiction == resource_jurisdiction:
            return True, []

        violations = []
        # Cross-border access hanya untuk role tertentu (kecuali data public)
        if (
            data_classification != DataClassification.PUBLIC
            and user_role not in self._allowed_cross_border_roles
        ):
            violations.append(
                f"User role '{user_role}' not authorized for cross-border access to {data_classification.value} data"
            )
        return len(violations) == 0, violations

    def record_transfer(
        self,
        data_type: DataClassification,
        source_jurisdiction: str,
        target_jurisdiction: str,
        transfer_basis: TransferBasis,
        amount_of_records: int | None = None,
        approved_by: UUID | None = None,
        justification: str = "",
    ) -> UUID:
        """Merekam transfer data lintas batas (untuk audit)."""
        transfer_id = uuid4()
        transfer = TransferRecord(
            transfer_id=transfer_id,
            data_type=data_type,
            source_jurisdiction=source_jurisdiction,
            target_jurisdiction=target_jurisdiction,
            transfer_basis=transfer_basis,
            amount_of_records=amount_of_records,
            approved_by=approved_by,
            justification=justification,
        )
        self._transfers.append(transfer)
        logger.info(
            f"Cross-border transfer recorded: {source_jurisdiction} -> {target_jurisdiction} ({data_type.value})"
        )
        return transfer_id

    def enforce_data_residency(
        self,
        data_source_jurisdiction: str,
        data_processing_jurisdiction: str,
        data_classification: DataClassification = DataClassification.PERSONAL,
    ) -> None:
        """Menegakkan aturan residensi data. Raise SovereigntyViolationError jika melanggar."""
        allowed, violations = self.check_data_residency(
            data_source_jurisdiction, data_processing_jurisdiction, data_classification
        )
        if not allowed:
            raise SovereigntyViolationError(
                f"Data sovereignty violation: {', '.join(violations)}",
                source_jurisdiction=data_source_jurisdiction,
                target_jurisdiction=data_processing_jurisdiction,
                data_type=data_classification.value,
            )

    def enforce_user_access(
        self,
        user_jurisdiction: str,
        resource_jurisdiction: str,
        user_role: str,
        data_classification: DataClassification = DataClassification.INTERNAL,
    ) -> None:
        """Menegakkan aturan akses user lintas batas."""
        allowed, violations = self.check_user_access(
            user_jurisdiction, resource_jurisdiction, user_role, data_classification
        )
        if not allowed:
            raise SovereigntyViolationError(
                f"Cross-border access violation: {', '.join(violations)}",
                source_jurisdiction=user_jurisdiction,
                target_jurisdiction=resource_jurisdiction,
                data_type=data_classification.value,
            )

    def get_transfer_history(self, limit: int = 100) -> list[TransferRecord]:
        return self._transfers[-limit:]

    def generate_report(self) -> dict:
        total_transfers = len(self._transfers)
        # FIX: tambahkan type annotation untuk menghilangkan error mypy
        by_source: dict[str, int] = {}
        by_target: dict[str, int] = {}
        by_type: dict[str, int] = {}
        for t in self._transfers:
            by_source[t.source_jurisdiction] = by_source.get(t.source_jurisdiction, 0) + 1
            by_target[t.target_jurisdiction] = by_target.get(t.target_jurisdiction, 0) + 1
            by_type[t.data_type.value] = by_type.get(t.data_type.value, 0) + 1
        return {
            "total_cross_border_transfers": total_transfers,
            "by_source_jurisdiction": by_source,
            "by_target_jurisdiction": by_target,
            "by_data_type": by_type,
        }

    def export_to_json(self, file_path: str) -> None:
        data = {
            "report": self.generate_report(),
            "transfers": [t.to_dict() for t in self._transfers],
        }
        with open(file_path, "w") as f:
            json.dump(data, f, indent=2, default=str)


# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    guard = SovereigntyBoundaryGuard()
    # Cek data residency
    allowed, violations = guard.check_data_residency("ID", "US", DataClassification.PERSONAL)
    print(f"Data residency ID->US for personal data: allowed={allowed}, violations={violations}")
    # Rekam transfer
    guard.record_transfer(
        data_type=DataClassification.PERSONAL,
        source_jurisdiction="ID",
        target_jurisdiction="SG",
        transfer_basis=TransferBasis.SCC,
        amount_of_records=1000,
        justification="Cloud backup with SCCs",
    )
    # Enforce
    try:
        guard.enforce_data_residency("ID", "XX", DataClassification.RESTRICTED)
    except SovereigntyViolationError as e:
        print(f"Violation caught: {e}")
    guard.export_to_json("sovereignty_boundary.json")
