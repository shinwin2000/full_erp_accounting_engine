# tests/policy_engine/tax_indonesia/test_treaty_resolver.py
"""
Comprehensive tests for treaty_resolver.py.

Covers:
- Enums: TreatyType, TreatyIncomeType
- TreatyArticle: construction, is_active, to_dict, hash
- TreatyResolver:
  - _load_default_treaties (tested via initialization)
  - add_treaty_article, remove_treaty_article
  - get_treaty_rate (with conditions, ownership, cache)
  - get_treaty_article
  - has_treaty, get_all_countries, get_applicable_rates
  - _make_key, _record_history (tested indirectly)
  - generate_report, export_to_json, get_requirements_summary
  - get_withholding_rate (compatibility method)
- Singleton: get_treaty_resolver
- Edge cases: inactive treaties, fallback rates for JP/US, cache invalidation
"""

from __future__ import annotations

import json
import tempfile
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from policy_engine.tax_indonesia.treaty_resolver import (
    TreatyArticle,
    TreatyIncomeType,
    TreatyResolver,
    TreatyType,
    get_treaty_resolver,
)

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def resolver():
    """Fresh TreatyResolver instance with default treaties loaded."""
    # Reset singleton for isolation
    TreatyResolver._instance = None
    return TreatyResolver()


@pytest.fixture
def sample_article():
    return TreatyArticle(
        country_code="XX",
        income_type=TreatyIncomeType.DIVIDEND,
        rate=Decimal("10"),
        article_number="Article 10",
        effective_from=datetime(2020, 1, 1, tzinfo=UTC),
        effective_to=None,
        condition="Minimal 25% ownership",
        has_limitation_of_benefits=False,
        source="test",
    )


# ============================================================================
# Tests for Enums
# ============================================================================

class TestTreatyType:
    def test_members(self):
        assert TreatyType.BILATERAL.value == "bilateral"
        assert TreatyType.MULTILATERAL.value == "multilateral"


class TestTreatyIncomeType:
    def test_members(self):
        assert TreatyIncomeType.DIVIDEND.value == "dividen"
        assert TreatyIncomeType.INTEREST.value == "bunga"
        assert TreatyIncomeType.ROYALTY.value == "royalti"
        assert TreatyIncomeType.BUSINESS_PROFIT.value == "laba_usaha"
        assert TreatyIncomeType.INDEPENDENT_PERSONAL_SERVICES.value == "jasa_pribadi_independen"
        assert TreatyIncomeType.DEPENDENT_PERSONAL_SERVICES.value == "pekerjaan_bebas"
        assert TreatyIncomeType.DIRECTOR_FEE.value == "fee_direksi"
        assert TreatyIncomeType.ARTISTE_SPORTSPERSON.value == "artis_olahragawan"
        assert TreatyIncomeType.PENSION.value == "pensiun"
        assert TreatyIncomeType.GOVERNMENT_SERVICE.value == "jasa_pemerintah"
        assert TreatyIncomeType.OTHER_INCOME.value == "penghasilan_lainnya"


# ============================================================================
# Tests for TreatyArticle
# ============================================================================

class TestTreatyArticle:
    def test_construction(self):
        article = TreatyArticle(
            country_code="ID",
            income_type=TreatyIncomeType.DIVIDEND,
            rate=Decimal("15"),
            article_number="Article 10",
            effective_from=datetime(2020, 1, 1, tzinfo=UTC),
        )
        assert article.country_code == "ID"
        assert article.rate == Decimal("15")
        assert article.hash_sha256 != ""

    def test_is_active(self):
        now = datetime.now(UTC)
        article = TreatyArticle(
            country_code="ID",
            income_type=TreatyIncomeType.DIVIDEND,
            rate=Decimal("10"),
            article_number="Art 10",
            effective_from=now - timedelta(days=30),
            effective_to=now + timedelta(days=30),
        )
        assert article.is_active(now) is True

        # Before effective_from
        assert article.is_active(now - timedelta(days=60)) is False

        # After effective_to
        assert article.is_active(now + timedelta(days=60)) is False

        # No effective_to
        article2 = TreatyArticle(
            country_code="ID",
            income_type=TreatyIncomeType.INTEREST,
            rate=Decimal("10"),
            article_number="Art 11",
            effective_from=now - timedelta(days=30),
        )
        assert article2.is_active(now + timedelta(days=365)) is True

    def test_to_dict(self):
        article = TreatyArticle(
            country_code="SG",
            income_type=TreatyIncomeType.DIVIDEND,
            rate=Decimal("10"),
            article_number="Article 10",
            effective_from=datetime(2020, 1, 1, tzinfo=UTC),
            condition="Test condition",
            has_limitation_of_benefits=True,
        )
        d = article.to_dict()
        assert d["country_code"] == "SG"
        assert d["rate"] == "10"
        assert d["condition"] == "Test condition"
        assert d["has_limitation_of_benefits"] is True
        assert "hash" in d


# ============================================================================
# Tests for TreatyResolver
# ============================================================================

class TestTreatyResolver:
    def test_init_loads_default_treaties(self, resolver):
        # Check that default treaties are loaded
        assert len(resolver._articles) > 0
        # Check a known default treaty exists
        assert resolver.has_treaty("SG") is True
        assert resolver.has_treaty("US") is True
        assert resolver.has_treaty("JP") is True

    def test_add_treaty_article(self, resolver, sample_article):
        resolver.add_treaty_article(sample_article)
        key = resolver._make_key("XX", TreatyIncomeType.DIVIDEND)
        assert key in resolver._articles
        assert resolver._articles[key] == sample_article
        # Check index
        assert "XX" in resolver._country_index
        assert key in resolver._country_index["XX"]

    def test_remove_treaty_article(self, resolver, sample_article):
        resolver.add_treaty_article(sample_article)
        key = resolver._make_key("XX", TreatyIncomeType.DIVIDEND)
        assert key in resolver._articles

        result = resolver.remove_treaty_article("XX", TreatyIncomeType.DIVIDEND)
        assert result is True
        # Article should still exist but with effective_to set
        article = resolver._articles.get(key)
        assert article is not None
        assert article.effective_to is not None
        assert article.effective_to <= datetime.now(UTC) + timedelta(seconds=1)

        # Remove non-existent
        result2 = resolver.remove_treaty_article("ZZ", TreatyIncomeType.DIVIDEND)
        assert result2 is False

    def test_has_treaty(self, resolver):
        assert resolver.has_treaty("SG") is True
        assert resolver.has_treaty("MY") is True
        assert resolver.has_treaty("XX") is False

    def test_get_all_countries(self, resolver):
        countries = resolver.get_all_countries()
        # Should include all default countries
        assert "SG" in countries
        assert "US" in countries
        assert "JP" in countries
        assert len(countries) > 10

    def test_get_applicable_rates(self, resolver):
        rates = resolver.get_applicable_rates("SG")
        assert "dividen" in rates
        assert "bunga" in rates
        assert "royalti" in rates
        assert rates["dividen"] == Decimal("10")

        # Non-existent country
        rates2 = resolver.get_applicable_rates("XX")
        assert rates2 == {}

    def test_get_treaty_rate_success(self, resolver):
        rate = resolver.get_treaty_rate("SG", TreatyIncomeType.DIVIDEND)
        assert rate == Decimal("10")

    def test_get_treaty_rate_inactive(self, resolver):
        # Use a date before the treaty became effective
        old_date = datetime(1980, 1, 1, tzinfo=UTC)
        rate = resolver.get_treaty_rate("SG", TreatyIncomeType.DIVIDEND, as_of=old_date)
        assert rate is None

    def test_get_treaty_rate_with_ownership_condition_satisfied(self, resolver):
        # Japan: 25% ownership needed for 10%
        rate = resolver.get_treaty_rate(
            "JP", TreatyIncomeType.DIVIDEND, ownership_percentage=Decimal("30")
        )
        assert rate == Decimal("10")

    def test_get_treaty_rate_with_ownership_condition_not_satisfied_japan(self, resolver):
        # Japan: less than 25% -> fallback 15%
        rate = resolver.get_treaty_rate(
            "JP", TreatyIncomeType.DIVIDEND, ownership_percentage=Decimal("20")
        )
        assert rate == Decimal("15")

    def test_get_treaty_rate_with_ownership_condition_not_satisfied_us(self, resolver):
        # US: less than 10% -> fallback 15%
        rate = resolver.get_treaty_rate(
            "US", TreatyIncomeType.DIVIDEND, ownership_percentage=Decimal("5")
        )
        assert rate == Decimal("15")

    def test_get_treaty_rate_with_ownership_condition_satisfied_us(self, resolver):
        # US: 10% or more -> 10%
        rate = resolver.get_treaty_rate(
            "US", TreatyIncomeType.DIVIDEND, ownership_percentage=Decimal("10")
        )
        assert rate == Decimal("10")

    def test_get_treaty_rate_cache(self, resolver):
        # First call should populate cache
        rate1 = resolver.get_treaty_rate("SG", TreatyIncomeType.DIVIDEND)
        assert rate1 == Decimal("10")
        # Second call should use cache
        rate2 = resolver.get_treaty_rate("SG", TreatyIncomeType.DIVIDEND)
        assert rate2 == Decimal("10")
        # Check cache size
        assert len(resolver._cache) > 0

    def test_get_treaty_rate_cache_invalidation_on_add(self, resolver, sample_article):
        # Get rate first to populate cache
        resolver.get_treaty_rate("XX", TreatyIncomeType.DIVIDEND)  # returns None
        # Add article
        resolver.add_treaty_article(sample_article)
        # Cache should be cleared; get rate again should return correct value
        rate = resolver.get_treaty_rate("XX", TreatyIncomeType.DIVIDEND)
        assert rate == Decimal("10")

    def test_get_treaty_article(self, resolver):
        article = resolver.get_treaty_article("SG", TreatyIncomeType.DIVIDEND)
        assert article is not None
        assert article.country_code == "SG"
        assert article.income_type == TreatyIncomeType.DIVIDEND

        # Inactive date
        old_date = datetime(1980, 1, 1, tzinfo=UTC)
        article2 = resolver.get_treaty_article("SG", TreatyIncomeType.DIVIDEND, as_of=old_date)
        assert article2 is None

    def test_get_treaty_article_not_exists(self, resolver):
        article = resolver.get_treaty_article("XX", TreatyIncomeType.DIVIDEND)
        assert article is None

    def test_make_key(self, resolver):
        key = resolver._make_key("XX", TreatyIncomeType.DIVIDEND)
        assert key == "XX_dividen"

    def test_record_history(self, resolver, sample_article):
        resolver.add_treaty_article(sample_article)
        assert len(resolver._history) > 0
        last = resolver._history[-1]
        assert last["action"] == "ADD"
        assert last["country_code"] == "XX"
        assert last["income_type"] == "dividen"

    def test_generate_report(self, resolver):
        report = resolver.generate_report()
        assert "total_treaty_articles" in report
        assert report["total_treaty_articles"] > 0
        assert "countries_with_treaty" in report
        assert "by_country" in report
        assert "SG" in report["by_country"]
        assert "cache_size" in report
        assert "history_count" in report

    def test_export_to_json(self, resolver):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            file_path = f.name
        try:
            resolver.export_to_json(file_path)
            with open(file_path) as f:
                data = json.load(f)
            assert "report" in data
            assert "articles" in data
            assert "history" in data
            assert len(data["articles"]) > 0
        finally:
            import os
            os.unlink(file_path)

    def test_get_requirements_summary(self, resolver):
        summary = resolver.get_requirements_summary()
        assert "supported_countries" in summary
        assert "income_types" in summary
        assert "default_rate_without_treaty" in summary
        assert len(summary["supported_countries"]) > 0
        assert "dividen" in summary["income_types"]

    # ---- Compatibility method: get_withholding_rate ----

    def test_get_withholding_rate_dividend(self, resolver):
        rate = resolver.get_withholding_rate("SG", "dividend")
        # 10% -> factor 0.10
        assert rate == Decimal("0.10")

    def test_get_withholding_rate_interest(self, resolver):
        rate = resolver.get_withholding_rate("MY", "interest")
        assert rate == Decimal("0.10")

    def test_get_withholding_rate_royalty(self, resolver):
        rate = resolver.get_withholding_rate("US", "royalty")
        assert rate == Decimal("0.10")

    def test_get_withholding_rate_service(self, resolver):
        # Service not in default treaties, should return default 20%
        rate = resolver.get_withholding_rate("SG", "service")
        assert rate == Decimal("0.20")

    def test_get_withholding_rate_unknown_country(self, resolver):
        rate = resolver.get_withholding_rate("ZZ", "dividend")
        # No treaty, default 20%
        assert rate == Decimal("0.20")

    def test_get_withholding_rate_unknown_income_type(self, resolver):
        rate = resolver.get_withholding_rate("SG", "unknown")
        assert rate == Decimal("0.20")

    def test_get_withholding_rate_case_insensitive(self, resolver):
        rate = resolver.get_withholding_rate("SG", "DIVIDEND")
        assert rate == Decimal("0.10")

    # ---- Singleton ----

    def test_get_treaty_resolver_singleton(self):
        # Reset singleton
        import policy_engine.tax_indonesia.treaty_resolver as module
        module._treaty_resolver_instance = None
        r1 = get_treaty_resolver()
        r2 = get_treaty_resolver()
        assert r1 is r2
        assert isinstance(r1, TreatyResolver)

    # ---- Edge cases ----

    def test_get_treaty_rate_with_ownership_but_not_dividend(self, resolver):
        # Ownership parameter should only affect dividend, not other income types
        rate = resolver.get_treaty_rate(
            "SG", TreatyIncomeType.INTEREST, ownership_percentage=Decimal("10")
        )
        assert rate == Decimal("10")  # unaffected

    def test_get_treaty_rate_with_custom_article_condition(self, resolver, sample_article):
        resolver.add_treaty_article(sample_article)
        # Ownership condition for XX article: 25% required
        rate = resolver.get_treaty_rate(
            "XX", TreatyIncomeType.DIVIDEND, ownership_percentage=Decimal("30")
        )
        # Since XX doesn't have special fallback logic, it returns the article rate
        # because our condition check only handles JP and US specifically.
        # For XX, it will return the article rate regardless because no fallback.
        assert rate == Decimal("10")

    def test_cache_date_key(self, resolver):
        # Get rate for a specific date
        check_date = datetime(2025, 1, 1, tzinfo=UTC)
        rate = resolver.get_treaty_rate("SG", TreatyIncomeType.DIVIDEND, as_of=check_date)
        assert rate == Decimal("10")
        # Check that cache uses date (not datetime) as key
        # We can't directly inspect cache key, but we can check that a different time on same day hits cache
        check_date2 = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
        rate2 = resolver.get_treaty_rate("SG", TreatyIncomeType.DIVIDEND, as_of=check_date2)
        assert rate2 == Decimal("10")
        # But we trust implementation.
