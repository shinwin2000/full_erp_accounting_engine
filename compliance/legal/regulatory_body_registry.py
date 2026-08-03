#!/usr/bin/env python3
"""
Module: regulatory_body_registry.py
Layer: Compliance / Legal

Responsibility:
    Registry badan regulator (OJK, DJP, BI, SEC, MAS, IRAS, FCA, ESMA, dll)
    beserta lingkup wewenang, yurisdiksi, website, API endpoints (jika ada),
    dan informasi kontak. Mendukung pencarian berdasarkan kode, nama, yurisdiksi,
    lingkup wewenang, serta ekspor ke JSON.

Dependencies:
    - datetime, typing, enum, hashlib, json, logging

Audit:
    Setiap penambahan atau perubahan regulator dicatat.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================
class RegulatoryScope(Enum):
    BANKING = "banking"
    CAPITAL_MARKET = "capital_market"
    INSURANCE = "insurance"
    TAXATION = "taxation"
    PENSION = "pension"
    SECURITIES = "securities"
    DERIVATIVES = "derivatives"
    CORPORATE = "corporate"
    AUDIT = "audit"
    ACCOUNTING = "accounting"
    DATA_PROTECTION = "data_protection"
    ANTI_MONEY_LAUNDERING = "anti_money_laundering"
    CONSUMER_PROTECTION = "consumer_protection"
    COMPETITION = "competition"
    PAYMENT_SYSTEM = "payment_system"
    MONETARY = "monetary"


# ============================================================================
# Data Classes
# ============================================================================
class RegulatoryBody:
    def __init__(
        self,
        code: str,
        name: str,
        jurisdiction: str,
        website: str = "",
        scopes: list[RegulatoryScope] | None = None,
        api_base_url: str | None = None,
        contact_email: str | None = None,
        contact_phone: str | None = None,
        description: str = "",
        is_active: bool = True,
    ):
        self.code = code.upper()
        self.name = name
        self.jurisdiction = jurisdiction
        self.website = website
        self.scopes = scopes or []
        self.api_base_url = api_base_url
        self.contact_email = contact_email
        self.contact_phone = contact_phone
        self.description = description
        self.is_active = is_active
        self.created_at = datetime.utcnow().isoformat()
        self._hash = self._compute_hash()

    def _compute_hash(self) -> str:
        data = {
            "code": self.code,
            "name": self.name,
            "jurisdiction": self.jurisdiction,
            "scopes": [s.value for s in self.scopes],
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "name": self.name,
            "jurisdiction": self.jurisdiction,
            "website": self.website,
            "scopes": [s.value for s in self.scopes],
            "api_base_url": self.api_base_url,
            "contact_email": self.contact_email,
            "contact_phone": self.contact_phone,
            "description": self.description,
            "is_active": self.is_active,
            "hash": self._hash,
        }


# ============================================================================
# RegulatoryBodyRegistry Core
# ============================================================================
class RegulatoryBodyRegistry:
    """
    Registry badan regulator dengan pencarian multi-kriteria.
    """

    def __init__(self):
        self._bodies: dict[str, RegulatoryBody] = {}
        self._jurisdiction_index: dict[str, list[str]] = {}
        self._scope_index: dict[str, list[str]] = {}
        self._init_default()

    def _init_default(self) -> None:
        """Inisialisasi regulator default (Indonesia, Singapore, US, UK, dll)."""
        regulators = [
            # Indonesia
            RegulatoryBody(
                "OJK",
                "Otoritas Jasa Keuangan",
                "ID",
                "https://ojk.go.id",
                scopes=[
                    RegulatoryScope.BANKING,
                    RegulatoryScope.CAPITAL_MARKET,
                    RegulatoryScope.INSURANCE,
                    RegulatoryScope.CONSUMER_PROTECTION,
                ],
                api_base_url="https://api.ojk.go.id/v1",
                contact_email="pengaduan@ojk.go.id",
                description="Indonesian Financial Services Authority",
            ),
            RegulatoryBody(
                "DJP",
                "Direktorat Jenderal Pajak",
                "ID",
                "https://pajak.go.id",
                scopes=[RegulatoryScope.TAXATION],
                api_base_url="https://api.pajak.go.id/v1",
                description="Directorate General of Taxes - Coretax",
            ),
            RegulatoryBody(
                "BI",
                "Bank Indonesia",
                "ID",
                "https://bi.go.id",
                scopes=[
                    RegulatoryScope.BANKING,
                    RegulatoryScope.PAYMENT_SYSTEM,
                    RegulatoryScope.MONETARY,
                ],
                description="Central Bank of Indonesia",
            ),
            RegulatoryBody(
                "KPPU",
                "Komisi Pengawas Persaingan Usaha",
                "ID",
                scopes=[RegulatoryScope.COMPETITION],
                description="Business Competition Supervisory Commission",
            ),
            # Singapore
            RegulatoryBody(
                "MAS",
                "Monetary Authority of Singapore",
                "SG",
                "https://mas.gov.sg",
                scopes=[
                    RegulatoryScope.BANKING,
                    RegulatoryScope.CAPITAL_MARKET,
                    RegulatoryScope.INSURANCE,
                    RegulatoryScope.SECURITIES,
                ],
                api_base_url="https://api.mas.gov.sg/v1",
                contact_email="mas_info@mas.gov.sg",
                description="Monetary Authority of Singapore",
            ),
            RegulatoryBody(
                "IRAS",
                "Inland Revenue Authority of Singapore",
                "SG",
                "https://iras.gov.sg",
                scopes=[RegulatoryScope.TAXATION],
                api_base_url="https://api.iras.gov.sg/v1",
                description="Singapore tax authority",
            ),
            RegulatoryBody(
                "ACRA",
                "Accounting and Corporate Regulatory Authority",
                "SG",
                "https://acra.gov.sg",
                scopes=[RegulatoryScope.CORPORATE, RegulatoryScope.ACCOUNTING],
                description="Business registration and corporate compliance",
            ),
            # United States
            RegulatoryBody(
                "SEC",
                "Securities and Exchange Commission",
                "US",
                "https://sec.gov",
                scopes=[RegulatoryScope.SECURITIES, RegulatoryScope.CAPITAL_MARKET],
                api_base_url="https://api.sec.gov/v1",
                description="U.S. Securities and Exchange Commission",
            ),
            RegulatoryBody(
                "IRS",
                "Internal Revenue Service",
                "US",
                "https://irs.gov",
                scopes=[RegulatoryScope.TAXATION],
                description="U.S. tax authority",
            ),
            RegulatoryBody(
                "FASB",
                "Financial Accounting Standards Board",
                "US",
                scopes=[RegulatoryScope.ACCOUNTING],
                description="U.S. accounting standards setter",
            ),
            RegulatoryBody(
                "PCAOB",
                "Public Company Accounting Oversight Board",
                "US",
                scopes=[RegulatoryScope.AUDIT],
                description="Audit oversight for public companies",
            ),
            # United Kingdom
            RegulatoryBody(
                "FCA",
                "Financial Conduct Authority",
                "UK",
                "https://fca.org.uk",
                scopes=[
                    RegulatoryScope.BANKING,
                    RegulatoryScope.SECURITIES,
                    RegulatoryScope.CONSUMER_PROTECTION,
                ],
                api_base_url="https://api.fca.org.uk/v1",
                description="Financial Conduct Authority",
            ),
            RegulatoryBody(
                "HMRC",
                "HM Revenue & Customs",
                "UK",
                "https://gov.uk/hmrc",
                scopes=[RegulatoryScope.TAXATION],
                description="UK tax authority",
            ),
            RegulatoryBody(
                "FRC",
                "Financial Reporting Council",
                "UK",
                scopes=[RegulatoryScope.ACCOUNTING, RegulatoryScope.AUDIT],
                description="UK accounting and audit regulator",
            ),
            # European Union
            RegulatoryBody(
                "ESMA",
                "European Securities and Markets Authority",
                "EU",
                "https://esma.europa.eu",
                scopes=[RegulatoryScope.SECURITIES, RegulatoryScope.CAPITAL_MARKET],
                description="EU securities regulator",
            ),
            RegulatoryBody(
                "EBA",
                "European Banking Authority",
                "EU",
                scopes=[RegulatoryScope.BANKING],
                description="EU banking regulator",
            ),
            RegulatoryBody(
                "EIOPA",
                "European Insurance and Occupational Pensions Authority",
                "EU",
                scopes=[RegulatoryScope.INSURANCE, RegulatoryScope.PENSION],
                description="EU insurance and pensions regulator",
            ),
            # Others
            RegulatoryBody(
                "IOSCO",
                "International Organization of Securities Commissions",
                "INTL",
                scopes=[RegulatoryScope.SECURITIES, RegulatoryScope.CAPITAL_MARKET],
                description="Global securities regulator forum",
            ),
            RegulatoryBody(
                "FATF",
                "Financial Action Task Force",
                "INTL",
                scopes=[RegulatoryScope.ANTI_MONEY_LAUNDERING],
                description="Global AML/CFT standard setter",
            ),
        ]
        for reg in regulators:
            self.register(reg)

    def register(self, body: RegulatoryBody) -> None:
        self._bodies[body.code] = body
        # Jurisdiction index
        self._jurisdiction_index.setdefault(body.jurisdiction, []).append(body.code)
        # Scope index
        for scope in body.scopes:
            self._scope_index.setdefault(scope.value, []).append(body.code)
        logger.info(f"Regulatory body registered: {body.code} - {body.name}")

    def get_body(self, code: str) -> RegulatoryBody | None:
        return self._bodies.get(code.upper())

    def get_bodies_by_jurisdiction(self, jurisdiction: str) -> list[RegulatoryBody]:
        codes = self._jurisdiction_index.get(jurisdiction, [])
        return [self._bodies[code] for code in codes if code in self._bodies]

    def get_bodies_by_scope(self, scope: RegulatoryScope) -> list[RegulatoryBody]:
        codes = self._scope_index.get(scope.value, [])
        return [self._bodies[code] for code in codes if code in self._bodies]

    def get_bodies_by_multiple_scopes(self, scopes: list[RegulatoryScope]) -> list[RegulatoryBody]:
        """Mengembalikan regulator yang mencakup semua scope yang diberikan."""
        result = []
        for body in self._bodies.values():
            body_scopes = {s.value for s in body.scopes}
            required = {s.value for s in scopes}
            if required.issubset(body_scopes):
                result.append(body)
        return result

    def search_by_name(self, keyword: str) -> list[RegulatoryBody]:
        keyword_lower = keyword.lower()
        return [b for b in self._bodies.values() if keyword_lower in b.name.lower()]

    def get_active_bodies(self) -> list[RegulatoryBody]:
        return [b for b in self._bodies.values() if b.is_active]

    def get_all(self) -> list[RegulatoryBody]:
        return list(self._bodies.values())

    def get_available_jurisdictions(self) -> list[str]:
        return list(self._jurisdiction_index.keys())

    def generate_report(self) -> dict:
        total = len(self._bodies)
        by_jurisdiction = {
            j: len(self.get_bodies_by_jurisdiction(j)) for j in self._jurisdiction_index
        }
        # Build set of all scope values used in the index
        all_scopes = {s for scope_list in self._scope_index.values() for s in scope_list}
        by_scope = {
            s: len(self.get_bodies_by_scope(RegulatoryScope(s))) for s in all_scopes
        }
        return {
            "total_bodies": total,
            "by_jurisdiction": by_jurisdiction,
            "by_scope": by_scope,
            "jurisdictions_covered": len(self._jurisdiction_index),
        }

    def export_to_json(self, file_path: str) -> None:
        data = {
            "report": self.generate_report(),
            "regulatory_bodies": [b.to_dict() for b in self._bodies.values()],
        }
        with open(file_path, "w") as f:
            json.dump(data, f, indent=2, default=str)


# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    registry = RegulatoryBodyRegistry()
    print("Total regulatory bodies:", len(registry.get_all()))
    print("Indonesian bodies:", [b.code for b in registry.get_bodies_by_jurisdiction("ID")])
    print(
        "Bodies with taxation scope:",
        [b.code for b in registry.get_bodies_by_scope(RegulatoryScope.TAXATION)],
    )
    registry.export_to_json("regulatory_bodies.json")
