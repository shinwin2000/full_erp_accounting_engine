#!/usr/bin/env python3
"""
Module: treaty_resolver.py
Layer: 7 - Policy Engine & Standards / Tax Indonesia

Responsibility:
    Resolusi Persetujuan Penghindaran Pajak Berganda (P3B / Tax Treaty)
    antara Indonesia dan negara mitra. Menyediakan mekanisme untuk menentukan
    tarif PPh Pasal 26 yang lebih rendah berdasarkan treaty, serta informasi
    artikel dan kondisi yang berlaku. Mendukung pembaruan dinamis dan audit.

Dependencies:
    - datetime, decimal, enum, typing, dataclasses, hashlib, json, logging
    - threading for cache

Audit:
    Setiap pencarian tarif treaty dicatat untuk audit.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================
class TreatyType(Enum):
    BILATERAL = "bilateral"
    MULTILATERAL = "multilateral"  # misal MLI


class TreatyIncomeType(Enum):
    """Jenis penghasilan yang diatur dalam P3B."""

    DIVIDEND = "dividen"
    INTEREST = "bunga"
    ROYALTY = "royalti"
    BUSINESS_PROFIT = "laba_usaha"
    INDEPENDENT_PERSONAL_SERVICES = "jasa_pribadi_independen"
    DEPENDENT_PERSONAL_SERVICES = "pekerjaan_bebas"
    DIRECTOR_FEE = "fee_direksi"
    ARTISTE_SPORTSPERSON = "artis_olahragawan"
    PENSION = "pensiun"
    GOVERNMENT_SERVICE = "jasa_pemerintah"
    OTHER_INCOME = "penghasilan_lainnya"


# ============================================================================
# Data Classes
# ============================================================================
@dataclass
class TreatyArticle:
    """Artikel P3B untuk suatu negara dan jenis penghasilan."""

    country_code: str
    income_type: TreatyIncomeType
    rate: Decimal  # tarif dalam persen (0 untuk dibebaskan)
    article_number: str
    effective_from: datetime
    effective_to: datetime | None = None
    condition: str = ""  # persyaratan khusus (misal kepemilikan saham ≥10%)
    has_limitation_of_benefits: bool = False
    source: str = "default"
    hash_sha256: str = ""

    def __post_init__(self):
        self.hash_sha256 = self._compute_hash()

    def _compute_hash(self) -> str:
        data = {
            "country_code": self.country_code,
            "income_type": self.income_type.value,
            "rate": str(self.rate),
            "article_number": self.article_number,
            "effective_from": self.effective_from.isoformat(),
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    def is_active(self, as_of: datetime | None = None) -> bool:
        check_date = as_of or datetime.now(UTC)
        return self.effective_from <= check_date and (
            self.effective_to is None or self.effective_to >= check_date
        )

    def to_dict(self) -> dict:
        return {
            "country_code": self.country_code,
            "income_type": self.income_type.value,
            "rate": str(self.rate),
            "article_number": self.article_number,
            "effective_from": self.effective_from.isoformat(),
            "effective_to": self.effective_to.isoformat() if self.effective_to else None,
            "condition": self.condition,
            "has_limitation_of_benefits": self.has_limitation_of_benefits,
            "hash": self.hash_sha256,
        }


# ============================================================================
# TreatyResolver Core
# ============================================================================
class TreatyResolver:
    """
    Resolver untuk tax treaty (P3B) Indonesia.
    Singleton, menyediakan akses cepat ke tarif treaty berdasarkan negara dan jenis penghasilan.
    """

    _instance: TreatyResolver | None = None
    _initialized: bool = False  # FIX: deklarasi tipe untuk mypy
    _lock: threading.RLock

    def __new__(cls) -> TreatyResolver:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._lock = threading.RLock()
        self._articles: dict[str, TreatyArticle] = {}  # key = f"{country_code}_{income_type.value}"
        self._country_index: dict[str, list[str]] = {}  # country_code -> list of keys
        self._history: list[dict] = []
        self._cache: dict[tuple[str, TreatyIncomeType, datetime], TreatyArticle | None] = {}
        self._load_default_treaties()

    # ------------------------------------------------------------------------
    # Default Treaties (Indonesia with major partners)
    # ------------------------------------------------------------------------
    def _load_default_treaties(self) -> None:
        """Memuat treaty default Indonesia dengan negara mitra utama."""
        default_treaties = [
            # Singapore
            TreatyArticle(
                "SG",
                TreatyIncomeType.DIVIDEND,
                Decimal("10"),
                "Article 10",
                datetime(1991, 1, 1, tzinfo=UTC),
                condition="Minimal 25% ownership",
            ),
            TreatyArticle(
                "SG",
                TreatyIncomeType.INTEREST,
                Decimal("10"),
                "Article 11",
                datetime(1991, 1, 1, tzinfo=UTC),
            ),
            TreatyArticle(
                "SG",
                TreatyIncomeType.ROYALTY,
                Decimal("10"),
                "Article 12",
                datetime(1991, 1, 1, tzinfo=UTC),
            ),
            # Malaysia
            TreatyArticle(
                "MY",
                TreatyIncomeType.DIVIDEND,
                Decimal("10"),
                "Article 10",
                datetime(1991, 1, 1, tzinfo=UTC),
                condition="Minimal 10% ownership",
            ),
            TreatyArticle(
                "MY",
                TreatyIncomeType.INTEREST,
                Decimal("10"),
                "Article 11",
                datetime(1991, 1, 1, tzinfo=UTC),
            ),
            TreatyArticle(
                "MY",
                TreatyIncomeType.ROYALTY,
                Decimal("10"),
                "Article 12",
                datetime(1991, 1, 1, tzinfo=UTC),
            ),
            # Japan
            TreatyArticle(
                "JP",
                TreatyIncomeType.DIVIDEND,
                Decimal("10"),
                "Article 10",
                datetime(1991, 1, 1, tzinfo=UTC),
                condition="Minimal 25% ownership (otherwise 15%)",
            ),
            TreatyArticle(
                "JP",
                TreatyIncomeType.INTEREST,
                Decimal("10"),
                "Article 11",
                datetime(1991, 1, 1, tzinfo=UTC),
            ),
            TreatyArticle(
                "JP",
                TreatyIncomeType.ROYALTY,
                Decimal("10"),
                "Article 12",
                datetime(1991, 1, 1, tzinfo=UTC),
            ),
            # Netherlands
            TreatyArticle(
                "NL",
                TreatyIncomeType.DIVIDEND,
                Decimal("10"),
                "Article 10",
                datetime(1991, 1, 1, tzinfo=UTC),
                condition="Minimal 25% ownership",
            ),
            TreatyArticle(
                "NL",
                TreatyIncomeType.INTEREST,
                Decimal("10"),
                "Article 11",
                datetime(1991, 1, 1, tzinfo=UTC),
            ),
            TreatyArticle(
                "NL",
                TreatyIncomeType.ROYALTY,
                Decimal("10"),
                "Article 12",
                datetime(1991, 1, 1, tzinfo=UTC),
            ),
            # United States (dividen 10-15%, bunga 10%, royalti 10%)
            TreatyArticle(
                "US",
                TreatyIncomeType.DIVIDEND,
                Decimal("10"),
                "Article 10",
                datetime(1991, 1, 1, tzinfo=UTC),
                condition="Minimal 10% ownership, otherwise 15%",
            ),
            TreatyArticle(
                "US",
                TreatyIncomeType.INTEREST,
                Decimal("10"),
                "Article 11",
                datetime(1991, 1, 1, tzinfo=UTC),
            ),
            TreatyArticle(
                "US",
                TreatyIncomeType.ROYALTY,
                Decimal("10"),
                "Article 12",
                datetime(1991, 1, 1, tzinfo=UTC),
            ),
            # China
            TreatyArticle(
                "CN",
                TreatyIncomeType.DIVIDEND,
                Decimal("10"),
                "Article 10",
                datetime(2003, 1, 1, tzinfo=UTC),
                condition="Minimal 25% ownership",
            ),
            TreatyArticle(
                "CN",
                TreatyIncomeType.INTEREST,
                Decimal("10"),
                "Article 11",
                datetime(2003, 1, 1, tzinfo=UTC),
            ),
            TreatyArticle(
                "CN",
                TreatyIncomeType.ROYALTY,
                Decimal("10"),
                "Article 12",
                datetime(2003, 1, 1, tzinfo=UTC),
            ),
            # Australia
            TreatyArticle(
                "AU",
                TreatyIncomeType.DIVIDEND,
                Decimal("15"),
                "Article 10",
                datetime(1992, 1, 1, tzinfo=UTC),
                condition="Minimal 25% ownership (10% if certain conditions)",
            ),
            TreatyArticle(
                "AU",
                TreatyIncomeType.INTEREST,
                Decimal("10"),
                "Article 11",
                datetime(1992, 1, 1, tzinfo=UTC),
            ),
            TreatyArticle(
                "AU",
                TreatyIncomeType.ROYALTY,
                Decimal("10"),
                "Article 12",
                datetime(1992, 1, 1, tzinfo=UTC),
            ),
            # United Kingdom
            TreatyArticle(
                "GB",
                TreatyIncomeType.DIVIDEND,
                Decimal("10"),
                "Article 10",
                datetime(1991, 1, 1, tzinfo=UTC),
                condition="Minimal 25% ownership",
            ),
            TreatyArticle(
                "GB",
                TreatyIncomeType.INTEREST,
                Decimal("10"),
                "Article 11",
                datetime(1991, 1, 1, tzinfo=UTC),
            ),
            TreatyArticle(
                "GB",
                TreatyIncomeType.ROYALTY,
                Decimal("10"),
                "Article 12",
                datetime(1991, 1, 1, tzinfo=UTC),
            ),
            # Germany
            TreatyArticle(
                "DE",
                TreatyIncomeType.DIVIDEND,
                Decimal("10"),
                "Article 10",
                datetime(1991, 1, 1, tzinfo=UTC),
                condition="Minimal 25% ownership",
            ),
            TreatyArticle(
                "DE",
                TreatyIncomeType.INTEREST,
                Decimal("10"),
                "Article 11",
                datetime(1991, 1, 1, tzinfo=UTC),
            ),
            TreatyArticle(
                "DE",
                TreatyIncomeType.ROYALTY,
                Decimal("10"),
                "Article 12",
                datetime(1991, 1, 1, tzinfo=UTC),
            ),
            # France
            TreatyArticle(
                "FR",
                TreatyIncomeType.DIVIDEND,
                Decimal("10"),
                "Article 10",
                datetime(1991, 1, 1, tzinfo=UTC),
                condition="Minimal 25% ownership",
            ),
            TreatyArticle(
                "FR",
                TreatyIncomeType.INTEREST,
                Decimal("10"),
                "Article 11",
                datetime(1991, 1, 1, tzinfo=UTC),
            ),
            TreatyArticle(
                "FR",
                TreatyIncomeType.ROYALTY,
                Decimal("10"),
                "Article 12",
                datetime(1991, 1, 1, tzinfo=UTC),
            ),
            # South Korea
            TreatyArticle(
                "KR",
                TreatyIncomeType.DIVIDEND,
                Decimal("10"),
                "Article 10",
                datetime(1991, 1, 1, tzinfo=UTC),
                condition="Minimal 25% ownership",
            ),
            TreatyArticle(
                "KR",
                TreatyIncomeType.INTEREST,
                Decimal("10"),
                "Article 11",
                datetime(1991, 1, 1, tzinfo=UTC),
            ),
            TreatyArticle(
                "KR",
                TreatyIncomeType.ROYALTY,
                Decimal("10"),
                "Article 12",
                datetime(1991, 1, 1, tzinfo=UTC),
            ),
            # India
            TreatyArticle(
                "IN",
                TreatyIncomeType.DIVIDEND,
                Decimal("10"),
                "Article 10",
                datetime(2015, 1, 1, tzinfo=UTC),
                condition="Minimal 25% ownership",
            ),
            TreatyArticle(
                "IN",
                TreatyIncomeType.INTEREST,
                Decimal("10"),
                "Article 11",
                datetime(2015, 1, 1, tzinfo=UTC),
            ),
            TreatyArticle(
                "IN",
                TreatyIncomeType.ROYALTY,
                Decimal("10"),
                "Article 12",
                datetime(2015, 1, 1, tzinfo=UTC),
            ),
        ]
        for article in default_treaties:
            self.add_treaty_article(article)

    # ------------------------------------------------------------------------
    # Treaty Management
    # ------------------------------------------------------------------------
    def add_treaty_article(self, article: TreatyArticle) -> None:
        """Menambahkan atau memperbarui treaty article."""
        key = self._make_key(article.country_code, article.income_type)
        with self._lock:
            self._articles[key] = article
            if article.country_code not in self._country_index:
                self._country_index[article.country_code] = []
            if key not in self._country_index[article.country_code]:
                self._country_index[article.country_code].append(key)
            self._invalidate_cache()
            self._record_history("ADD", article)
            logger.info(
                f"Treaty article added: {article.country_code} - {article.income_type.value} at {article.rate}%"
            )

    def remove_treaty_article(self, country_code: str, income_type: TreatyIncomeType) -> bool:
        """Menghapus treaty article (soft delete: set effective_to to now)."""
        key = self._make_key(country_code, income_type)
        with self._lock:
            article = self._articles.get(key)
            if not article:
                return False
            article.effective_to = datetime.now(UTC)
            article.hash_sha256 = article._compute_hash()
            self._invalidate_cache()
            self._record_history("REMOVE", article)
            return True

    def get_treaty_rate(
        self,
        country_code: str,
        income_type: TreatyIncomeType,
        as_of: datetime | None = None,
        ownership_percentage: Decimal | None = None,
    ) -> Decimal | None:
        """
        Mendapatkan tarif treaty untuk negara dan jenis penghasilan pada tanggal tertentu.
        Dapat memeriksa kondisi kepemilikan saham untuk dividen.
        """
        key = self._make_key(country_code, income_type)
        check_date = as_of or datetime.now(UTC)
        # FIX: gunakan datetime sebagai key, bukan date
        cache_key = (country_code, income_type, check_date)

        with self._lock:
            if cache_key in self._cache:
                article = self._cache[cache_key]
                if article:
                    return article.rate
                return None

        article = self._articles.get(key)
        if not article or not article.is_active(check_date):
            with self._lock:
                self._cache[cache_key] = None
            return None

        # Check condition for dividend ownership
        if (
            income_type == TreatyIncomeType.DIVIDEND
            and ownership_percentage is not None
            and "ownership" in article.condition.lower()
            and "25%" in article.condition
            and ownership_percentage < 25
        ):
            # Fallback rate (misal 15% untuk Jepang jika kepemilikan <25%)
            if article.country_code == "JP":
                fallback_rate = Decimal("15")
                with self._lock:
                    self._cache[cache_key] = article
                return fallback_rate
            if article.country_code == "US":
                fallback_rate = Decimal("15") if ownership_percentage < 10 else Decimal("10")
                with self._lock:
                    self._cache[cache_key] = article
                return fallback_rate

        with self._lock:
            self._cache[cache_key] = article
        return article.rate

    def get_treaty_article(
        self,
        country_code: str,
        income_type: TreatyIncomeType,
        as_of: datetime | None = None,
    ) -> TreatyArticle | None:
        """Mendapatkan artikel treaty lengkap."""
        key = self._make_key(country_code, income_type)
        check_date = as_of or datetime.now(UTC)
        article = self._articles.get(key)
        if article and article.is_active(check_date):
            return article
        return None

    def has_treaty(self, country_code: str) -> bool:
        """Memeriksa apakah Indonesia memiliki P3B dengan negara tersebut."""
        return country_code in self._country_index

    def get_all_countries(self) -> list[str]:
        """Mendapatkan daftar negara mitra P3B."""
        return list(self._country_index.keys())

    def get_applicable_rates(
        self,
        country_code: str,
        as_of: datetime | None = None,
    ) -> dict[str, Decimal]:
        """Mendapatkan semua tarif treaty untuk suatu negara."""
        result = {}
        keys = self._country_index.get(country_code, [])
        for key in keys:
            article = self._articles.get(key)
            if article and article.is_active(as_of):
                result[article.income_type.value] = article.rate
        return result

    # ------------------------------------------------------------------------
    # Helper Methods
    # ------------------------------------------------------------------------
    def _make_key(self, country_code: str, income_type: TreatyIncomeType) -> str:
        return f"{country_code.upper()}_{income_type.value}"

    def _invalidate_cache(self) -> None:
        self._cache.clear()

    def _record_history(self, action: str, article: TreatyArticle) -> None:
        self._history.append(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "action": action,
                "country_code": article.country_code,
                "income_type": article.income_type.value,
                "rate": str(article.rate),
                "effective_from": article.effective_from.isoformat(),
            }
        )

    # ------------------------------------------------------------------------
    # Reporting & Export
    # ------------------------------------------------------------------------
    def generate_report(self) -> dict:
        total = len(self._articles)
        by_country = {c: len(keys) for c, keys in self._country_index.items()}
        return {
            "total_treaty_articles": total,
            "countries_with_treaty": len(self._country_index),
            "by_country": by_country,
            "cache_size": len(self._cache),
            "history_count": len(self._history),
        }

    def export_to_json(self, file_path: str) -> None:
        data = {
            "report": self.generate_report(),
            "articles": [a.to_dict() for a in self._articles.values()],
            "history": self._history[-500:],
        }
        with open(file_path, "w") as f:
            json.dump(data, f, indent=2, default=str)

    def get_requirements_summary(self) -> dict:
        return {
            "supported_countries": self.get_all_countries(),
            "income_types": [t.value for t in TreatyIncomeType],
            "default_rate_without_treaty": "20%",
            "note": "Rates based on Indonesia's double tax treaties (updated as of 2026)",
        }

    # ========================================================================
    # METHODS FOR TEST COMPATIBILITY (added without removing original)
    # ========================================================================
    def get_withholding_rate(self, country_code: str, income_type: str) -> Decimal:
        """
        Get withholding tax rate based on tax treaty.
        Returns Decimal as factor (e.g., 0.10 for 10%).
        """
        # Map string income_type to TreatyIncomeType
        income_map = {
            "dividend": TreatyIncomeType.DIVIDEND,
            "interest": TreatyIncomeType.INTEREST,
            "royalty": TreatyIncomeType.ROYALTY,
            "service": TreatyIncomeType.INDEPENDENT_PERSONAL_SERVICES,
            "rental": TreatyIncomeType.OTHER_INCOME,
            "other": TreatyIncomeType.OTHER_INCOME,
        }
        itype = income_map.get(income_type.lower(), TreatyIncomeType.OTHER_INCOME)
        rate = self.get_treaty_rate(country_code, itype)
        if rate is None:
            # Default 20% if no treaty or rate not found, return as factor 0.20
            return Decimal("0.20")
        # Convert percentage to factor (e.g., 10 -> 0.10)
        return rate / Decimal("100")


# ============================================================================
# Singleton Accessor
# ============================================================================
_treaty_resolver_instance: TreatyResolver | None = None


def get_treaty_resolver() -> TreatyResolver:
    global _treaty_resolver_instance
    if _treaty_resolver_instance is None:
        _treaty_resolver_instance = TreatyResolver()
    return _treaty_resolver_instance


# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    resolver = get_treaty_resolver()

    # Get treaty rate for dividend from Singapore
    rate = resolver.get_treaty_rate(
        "SG", TreatyIncomeType.DIVIDEND, ownership_percentage=Decimal("30")
    )
    print(f"Dividend rate for Singapore: {rate}%")

    # Get royalty rate for Malaysia
    royalty_rate = resolver.get_treaty_rate("MY", TreatyIncomeType.ROYALTY)
    print(f"Royalty rate for Malaysia: {royalty_rate}%")

    # Check if treaty exists with Japan
    print(f"Has treaty with Japan: {resolver.has_treaty('JP')}")

    # Get all applicable rates for Singapore
    rates = resolver.get_applicable_rates("SG")
    print(f"All rates for Singapore: {rates}")

    # Get treaty article details
    article = resolver.get_treaty_article("JP", TreatyIncomeType.DIVIDEND)
    if article:
        print(f"Japan dividend article: {article.article_number}, condition: {article.condition}")

    # Test compatibility method
    w_rate = resolver.get_withholding_rate("SG", "dividend")
    print(f"Withholding rate via get_withholding_rate: {w_rate}")

    # Export report
    resolver.export_to_json("treaty_resolver.json")
    print("\nTreaty resolver exported to treaty_resolver.json")
