#!/usr/bin/env python3
"""
Module: coretax_legal_basis_catalog.py
Layer: Compliance / Legal

Responsibility:
    Katalog basis legal untuk Coretax DJP Indonesia, termasuk Undang-Undang,
    Peraturan Menteri Keuangan (PMK), Peraturan Direktur Jenderal Pajak (PER-DJP),
    dan Surat Edaran (SE). Mendukung pencarian berdasarkan kata kunci, nomor,
    tahun, status berlaku (aktif/superseded), dan menyediakan referensi silang
    ke aturan yang menggantikan.

Dependencies:
    - datetime, typing, enum, hashlib, json, logging

Audit:
    Setiap akses ke basis hukum dicatat (optional). Katalog memiliki hash integrity.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================
class LegalBasisType(Enum):
    LAW = "undang_undang"  # UU
    GOVERNMENT_REGULATION = "peraturan_pemerintah"  # PP
    PRESIDENTIAL_REGULATION = "peraturan_presiden"  # PERPRES
    MINISTERIAL_REGULATION = "peraturan_menteri"  # PMK (Permenkeu)
    DIRECTOR_GENERAL_REGULATION = "peraturan_dirjen"  # PER-DJP
    CIRCULAR_LETTER = "surat_edaran"  # SE
    DECREE = "keputusan"  # KEP
    INSTRUCTION = "instruksi"  # INSTR


class LegalBasisStatus(Enum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    REPEALED = "repealed"
    EXPIRED = "expired"


# ============================================================================
# Data Classes
# ============================================================================
class LegalBasis:
    def __init__(
        self,
        id: UUID,
        citation: str,  # e.g., "UU No. 7 Tahun 2021"
        title: str,
        basis_type: LegalBasisType,
        issued_date: str,
        effective_date: str,
        issuing_body: str,
        summary: str,
        articles: list[str],
        related_to_coretax: bool = True,
        status: LegalBasisStatus = LegalBasisStatus.ACTIVE,
        superseded_by: str | None = None,
        url: str | None = None,
    ):
        self.id = id
        self.citation = citation
        self.title = title
        self.basis_type = basis_type
        self.issued_date = issued_date
        self.effective_date = effective_date
        self.issuing_body = issuing_body
        self.summary = summary
        self.articles = articles
        self.related_to_coretax = related_to_coretax
        self.status = status
        self.superseded_by = superseded_by
        self.url = url
        self.created_at = datetime.utcnow().isoformat()
        self._hash = self._compute_hash()

    def _compute_hash(self) -> str:
        data = {
            "id": str(self.id),
            "citation": self.citation,
            "title": self.title,
            "type": self.basis_type.value,
            "status": self.status.value,
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    def supersede(self, new_citation: str) -> None:
        self.status = LegalBasisStatus.SUPERSEDED
        self.superseded_by = new_citation
        self._hash = self._compute_hash()

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "citation": self.citation,
            "title": self.title,
            "basis_type": self.basis_type.value,
            "issued_date": self.issued_date,
            "effective_date": self.effective_date,
            "issuing_body": self.issuing_body,
            "summary": self.summary,
            "articles": self.articles,
            "related_to_coretax": self.related_to_coretax,
            "status": self.status.value,
            "superseded_by": self.superseded_by,
            "url": self.url,
            "hash": self._hash,
        }


# ============================================================================
# CoretaxLegalBasisCatalog Core
# ============================================================================
class CoretaxLegalBasisCatalog:
    """
    Katalog basis legal untuk Coretax DJP.
    """

    def __init__(self) -> None:  # FIX: tambahkan anotasi tipe
        self._catalog: dict[str, LegalBasis] = {}
        self._load_catalog()

    def _load_catalog(self) -> None:  # FIX: tambahkan anotasi tipe
        """Memuat basis legal dari data internal (bisa diperluas dengan file eksternal)."""
        # Undang-Undang
        self.add_basis(
            LegalBasis(
                id=uuid4(),
                citation="UU No. 7 Tahun 2021",
                title="Harmonisasi Peraturan Perpajakan (HPP)",
                basis_type=LegalBasisType.LAW,
                issued_date="2021-10-29",
                effective_date="2022-04-01",
                issuing_body="DPR & Pemerintah",
                summary="Mengatur perubahan tarif PPN menjadi 11% (2022) dan 12% (2025), serta perubahan PPh",
                articles=["Pasal 2", "Pasal 7", "Pasal 9"],
                related_to_coretax=True,
            )
        )
        self.add_basis(
            LegalBasis(
                id=uuid4(),
                citation="UU No. 6 Tahun 1983",
                title="Ketentuan Umum dan Tata Cara Perpajakan (KUP)",
                basis_type=LegalBasisType.LAW,
                issued_date="1983-12-19",
                effective_date="1984-01-01",
                issuing_body="DPR",
                summary="Dasar hukum administrasi perpajakan, termasuk NPWP, SPT, pemeriksaan",
                articles=["Pasal 1", "Pasal 2", "Pasal 3"],
                related_to_coretax=True,
            )
        )

        # PMK (Peraturan Menteri Keuangan)
        self.add_basis(
            LegalBasis(
                id=uuid4(),
                citation="PMK No. 1/PMK.03/2024",
                title="Sistem Coretax Administrasi Perpajakan",
                basis_type=LegalBasisType.MINISTERIAL_REGULATION,
                issued_date="2024-01-05",
                effective_date="2024-07-01",
                issuing_body="Menteri Keuangan",
                summary="Dasar hukum implementasi Coretax DJP, termasuk kewajiban wajib pajak menggunakan sistem",
                articles=["Pasal 1-15", "Pasal 20"],
                related_to_coretax=True,
            )
        )
        self.add_basis(
            LegalBasis(
                id=uuid4(),
                citation="PMK No. 68/PMK.03/2022",
                title="Faktur Pajak",
                basis_type=LegalBasisType.MINISTERIAL_REGULATION,
                issued_date="2022-05-30",
                effective_date="2022-07-01",
                issuing_body="Menteri Keuangan",
                summary="Format, tata cara pembuatan, pembetulan, dan pembatalan faktur pajak",
                articles=["Pasal 1-25"],
                related_to_coretax=True,
            )
        )
        self.add_basis(
            LegalBasis(
                id=uuid4(),
                citation="PMK No. 60/PMK.03/2022",
                title="Bukti Potong PPh 21/26",
                basis_type=LegalBasisType.MINISTERIAL_REGULATION,
                issued_date="2022-05-11",
                effective_date="2022-07-01",
                issuing_body="Menteri Keuangan",
                summary="Tata cara pembuatan bukti potong PPh 21/26 melalui aplikasi e-Bupot",
                articles=["Pasal 1-12"],
                related_to_coretax=True,
            )
        )

        # PER-DJP (Peraturan Direktur Jenderal Pajak)
        self.add_basis(
            LegalBasis(
                id=uuid4(),
                citation="PER-03/PJ/2024",
                title="Faktur Pajak dalam Coretax",
                basis_type=LegalBasisType.DIRECTOR_GENERAL_REGULATION,
                issued_date="2024-02-15",
                effective_date="2024-07-01",
                issuing_body="Dirjen Pajak",
                summary="Petunjuk teknis pembuatan faktur pajak di Coretax, termasuk kode transaksi dan QR code",
                articles=["Pasal 1-30"],
                related_to_coretax=True,
            )
        )
        self.add_basis(
            LegalBasis(
                id=uuid4(),
                citation="PER-04/PJ/2024",
                title="e-Bupot PPh 23/26 di Coretax",
                basis_type=LegalBasisType.DIRECTOR_GENERAL_REGULATION,
                issued_date="2024-02-10",
                effective_date="2024-07-01",
                issuing_body="Dirjen Pajak",
                summary="Petunjuk teknis pembuatan bukti potong PPh 23/26 melalui Coretax",
                articles=["Pasal 1-25"],
                related_to_coretax=True,
            )
        )
        self.add_basis(
            LegalBasis(
                id=uuid4(),
                citation="PER-07/PJ/2024",
                title="e-Meterai Coretax",
                basis_type=LegalBasisType.DIRECTOR_GENERAL_REGULATION,
                issued_date="2024-03-01",
                effective_date="2024-07-01",
                issuing_body="Dirjen Pajak",
                summary="Tata cara pembubuhan e-Meterai pada dokumen elektronik",
                articles=["Pasal 1-18"],
                related_to_coretax=True,
            )
        )
        self.add_basis(
            LegalBasis(
                id=uuid4(),
                citation="PER-11/PJ/2024",
                title="NTPN dan Validasi Pembayaran",
                basis_type=LegalBasisType.DIRECTOR_GENERAL_REGULATION,
                issued_date="2024-03-15",
                effective_date="2024-07-01",
                issuing_body="Dirjen Pajak",
                summary="Tata cara validasi NTPN (Nomor Tanda Penerimaan Negara) di Coretax",
                articles=["Pasal 1-12"],
                related_to_coretax=True,
            )
        )

        # Surat Edaran (SE)
        self.add_basis(
            LegalBasis(
                id=uuid4(),
                citation="SE-11/PJ/2024",
                title="Sosialisasi Coretax",
                basis_type=LegalBasisType.CIRCULAR_LETTER,
                issued_date="2024-04-01",
                effective_date="2024-04-01",
                issuing_body="Dirjen Pajak",
                summary="Sosialisasi implementasi Coretax kepada wajib pajak",
                articles=[],
                related_to_coretax=True,
            )
        )

    def add_basis(self, basis: LegalBasis) -> None:
        self._catalog[basis.citation] = basis

    def get_basis(self, citation: str) -> LegalBasis | None:
        return self._catalog.get(citation)

    def search_by_keyword(self, keyword: str, case_sensitive: bool = False) -> list[LegalBasis]:
        keyword_lower = keyword if case_sensitive else keyword.lower()
        result = []
        for basis in self._catalog.values():
            title_match = (
                (keyword in basis.title)
                if case_sensitive
                else (keyword_lower in basis.title.lower())
            )
            summary_match = (
                (keyword in basis.summary)
                if case_sensitive
                else (keyword_lower in basis.summary.lower())
            )
            citation_match = (
                (keyword in basis.citation)
                if case_sensitive
                else (keyword_lower in basis.citation.lower())
            )
            if title_match or summary_match or citation_match:
                result.append(basis)
        return result

    def search_by_type(self, basis_type: LegalBasisType) -> list[LegalBasis]:
        return [b for b in self._catalog.values() if b.basis_type == basis_type]

    def get_active_bases(self) -> list[LegalBasis]:
        return [b for b in self._catalog.values() if b.status == LegalBasisStatus.ACTIVE]

    def search_by_year(self, year: int) -> list[LegalBasis]:
        # FIX: konversi year ke string agar operator 'in' berfungsi dengan benar
        year_str = str(year)
        return [b for b in self._catalog.values() if year_str in b.issued_date]

    def get_related_to_coretax(self) -> list[LegalBasis]:
        return [b for b in self._catalog.values() if b.related_to_coretax]

    def list_all(self) -> list[LegalBasis]:
        return list(self._catalog.values())

    def export_to_json(self, file_path: str) -> None:
        data = {
            "total": len(self._catalog),
            "bases": [b.to_dict() for b in self._catalog.values()],
        }
        with open(file_path, "w") as f:
            json.dump(data, f, indent=2, default=str)


# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    catalog = CoretaxLegalBasisCatalog()
    print("Total legal bases:", len(catalog.list_all()))
    for b in catalog.search_by_type(LegalBasisType.DIRECTOR_GENERAL_REGULATION):
        print(f"- {b.citation}: {b.title}")
    catalog.export_to_json("coretax_legal_basis.json")
