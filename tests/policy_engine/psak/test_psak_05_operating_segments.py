# tests/policy_engine/psak/test_psak_05_operating_segments.py
# Comprehensive tests for psak_05_operating_segments.py

import json
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from policy_engine.psak.psak_05_operating_segments import (
    PSAK5AggregationCriteria,
    PSAK5ComplianceLevel,
    PSAK5Error,
    PSAK5Rules,
    PSAK5Segment,
    PSAK5SegmentDisclosure,
    PSAK5SegmentService,
    PSAK5SegmentType,
    PSAK5ValidationResult,
    PSAK5Validator,
    SegmentNotFoundError,
    SegmentReportableStatus,
    get_psak5_validator,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def sample_segment():
    return PSAK5Segment(
        segment_id=uuid4(),
        segment_name="Produk Elektronik",
        segment_type=PSAK5SegmentType.BUSINESS,
        is_reportable=True,
        revenue_external=Decimal("5000000000"),
        revenue_internal=Decimal("1000000000"),
        profit_loss=Decimal("800000000"),
        assets=Decimal("3000000000"),
        liabilities=Decimal("1000000000"),
        capital_expenditure=Decimal("200000000"),
        depreciation=Decimal("150000000"),
        amortization=Decimal("50000000"),
        non_cash_expenses=Decimal("30000000"),
    )


@pytest.fixture
def sample_segment_small():
    return PSAK5Segment(
        segment_id=uuid4(),
        segment_name="Jasa Konsultasi",
        segment_type=PSAK5SegmentType.BUSINESS,
        revenue_external=Decimal("300000000"),
        profit_loss=Decimal("50000000"),
        assets=Decimal("200000000"),
    )


@pytest.fixture
def sample_segments(sample_segment, sample_segment_small):
    return [sample_segment, sample_segment_small]


@pytest.fixture
def sample_disclosure(sample_segments):
    return PSAK5SegmentDisclosure(
        disclosure_id=uuid4(),
        entity_id=uuid4(),
        entity_name="PT Contoh Segmentasi",
        reporting_period_end=datetime(2026, 12, 31, tzinfo=UTC),
        segments=sample_segments,
        entity_wide_disclosures={
            "product_disclosures": "Pendapatan: Elektronik 5M, Furniture 2M, Jasa 300jt",
            "geographic_disclosures": "Domestik 6.5M, Ekspor 800jt",
            "major_customers": "Pelanggan A (15%), Pelanggan B (12%)",
        },
    )


@pytest.fixture
def validator():
    return PSAK5Validator()


# ============================================================================
# Tests for Enums (already present, keep them)
# ============================================================================

class TestPSAK5SegmentType:
    def test_members_exist(self):
        assert hasattr(PSAK5SegmentType, 'BUSINESS')
        assert hasattr(PSAK5SegmentType, 'GEOGRAPHICAL')
        assert hasattr(PSAK5SegmentType, 'BOTH')

    def test_member_is_instance(self):
        assert isinstance(PSAK5SegmentType.BUSINESS, PSAK5SegmentType)


class TestPSAK5AggregationCriteria:
    def test_members_exist(self):
        assert hasattr(PSAK5AggregationCriteria, 'SIMILAR_ECONOMIC_CHARACTERISTICS')
        assert hasattr(PSAK5AggregationCriteria, 'SIMILAR_PRODUCTS')
        assert hasattr(PSAK5AggregationCriteria, 'SIMILAR_PRODUCTION')
        assert hasattr(PSAK5AggregationCriteria, 'SIMILAR_CUSTOMERS')
        assert hasattr(PSAK5AggregationCriteria, 'SIMILAR_DISTRIBUTION')

    def test_member_is_instance(self):
        assert isinstance(PSAK5AggregationCriteria.SIMILAR_ECONOMIC_CHARACTERISTICS, PSAK5AggregationCriteria)


class TestPSAK5ComplianceLevel:
    def test_members_exist(self):
        assert hasattr(PSAK5ComplianceLevel, 'FULL')
        assert hasattr(PSAK5ComplianceLevel, 'SUBSTANTIAL')
        assert hasattr(PSAK5ComplianceLevel, 'PARTIAL')
        assert hasattr(PSAK5ComplianceLevel, 'NON_COMPLIANT')

    def test_member_is_instance(self):
        assert isinstance(PSAK5ComplianceLevel.FULL, PSAK5ComplianceLevel)


class TestSegmentReportableStatus:
    def test_members_exist(self):
        assert hasattr(SegmentReportableStatus, 'REPORTABLE')
        assert hasattr(SegmentReportableStatus, 'NON_REPORTABLE')

    def test_member_is_instance(self):
        assert isinstance(SegmentReportableStatus.REPORTABLE, SegmentReportableStatus)


# ============================================================================
# Tests for Exceptions
# ============================================================================

class TestPSAK5Error:
    def test_raise(self):
        with pytest.raises(PSAK5Error):
            raise PSAK5Error("test")


class TestSegmentNotFoundError:
    def test_raise(self):
        with pytest.raises(SegmentNotFoundError):
            raise SegmentNotFoundError("not found")


# ============================================================================
# Tests for PSAK5Segment
# ============================================================================

class TestPSAK5Segment:
    def test_construction(self, sample_segment):
        assert sample_segment.segment_name == "Produk Elektronik"
        assert sample_segment.segment_type == PSAK5SegmentType.BUSINESS
        assert sample_segment.revenue_external == Decimal("5000000000")
        assert sample_segment.total_revenue == Decimal("6000000000")  # external + internal

    def test_compute_profit_margin(self, sample_segment):
        margin = sample_segment.compute_profit_margin()
        # profit_loss / total_revenue * 100 = 800,000,000 / 6,000,000,000 * 100 = 13.33%
        expected = (Decimal("800000000") / Decimal("6000000000")) * 100
        assert margin == expected.quantize(Decimal("0.01"))

    def test_compute_profit_margin_zero_revenue(self):
        seg = PSAK5Segment(
            segment_id=uuid4(),
            segment_name="Zero Revenue",
            segment_type=PSAK5SegmentType.BUSINESS,
            profit_loss=Decimal("100000"),
            revenue_external=Decimal(0),
            revenue_internal=Decimal(0),
        )
        assert seg.compute_profit_margin() == Decimal(0)

    def test_to_dict(self, sample_segment):
        d = sample_segment.to_dict()
        assert d["segment_name"] == "Produk Elektronik"
        assert d["segment_type"] == "bisnis"
        assert d["revenue_external"] == "5000000000"
        assert d["total_revenue"] == "6000000000"
        assert "profit_margin" in d


# ============================================================================
# Tests for PSAK5SegmentDisclosure
# ============================================================================

class TestPSAK5SegmentDisclosure:
    def test_construction(self, sample_disclosure):
        assert sample_disclosure.entity_name == "PT Contoh Segmentasi"
        assert len(sample_disclosure.segments) == 2

    def test_total_external_revenue(self, sample_disclosure):
        total = sample_disclosure.total_external_revenue()
        # 5,000,000,000 + 300,000,000 = 5,300,000,000
        assert total == Decimal("5300000000")

    def test_total_reportable_segments(self, sample_disclosure):
        # Both segments are reportable (default is True)
        reportable = sample_disclosure.total_reportable_segments()
        assert len(reportable) == 2
        # If we set one to non-reportable
        sample_disclosure.segments[0].is_reportable = False
        reportable2 = sample_disclosure.total_reportable_segments()
        assert len(reportable2) == 1

    def test_segment_count(self, sample_disclosure):
        assert sample_disclosure.segment_count() == 2
        # With non-reportable
        sample_disclosure.segments[0].is_reportable = False
        assert sample_disclosure.segment_count() == 1

    def test_to_dict(self, sample_disclosure):
        d = sample_disclosure.to_dict()
        assert d["entity_name"] == "PT Contoh Segmentasi"
        assert d["segment_count"] == 2
        assert d["total_external_revenue"] == "5300000000"
        assert len(d["segments"]) == 2
        assert "reconciliation_revenue" in d


# ============================================================================
# Tests for PSAK5ValidationResult
# ============================================================================

class TestPSAK5ValidationResult:
    def test_initialization(self):
        result = PSAK5ValidationResult(
            is_compliant=True,
            compliance_level=PSAK5ComplianceLevel.FULL,
        )
        assert result.is_compliant is True
        assert result.compliance_level == PSAK5ComplianceLevel.FULL
        assert result.hash_sha256 != ""

    def test_add_error(self):
        result = PSAK5ValidationResult(is_compliant=True, compliance_level=PSAK5ComplianceLevel.FULL)
        result.add_error("Error message")
        assert result.is_compliant is False
        assert result.compliance_level == PSAK5ComplianceLevel.NON_COMPLIANT
        assert "Error message" in result.errors

    def test_add_warning(self):
        result = PSAK5ValidationResult(is_compliant=True, compliance_level=PSAK5ComplianceLevel.FULL)
        result.add_warning("Warning message")
        assert result.is_compliant is True
        assert result.compliance_level == PSAK5ComplianceLevel.SUBSTANTIAL
        assert "Warning message" in result.warnings

    def test_to_dict(self):
        result = PSAK5ValidationResult(
            is_compliant=False,
            compliance_level=PSAK5ComplianceLevel.NON_COMPLIANT,
            errors=["e1"],
            warnings=["w1"],
        )
        d = result.to_dict()
        assert d["is_compliant"] is False
        assert d["compliance_level"] == "tidak_patuh"
        assert d["errors"] == ["e1"]
        assert d["warnings"] == ["w1"]
        assert "hash" in d


# ============================================================================
# Tests for PSAK5SegmentService
# ============================================================================

class TestPSAK5SegmentService:
    def test_identify_reportable_segments(self, sample_segments):
        # All segments are reportable by default, so we need to reset is_reportable
        for seg in sample_segments:
            seg.is_reportable = False
        reportable = PSAK5SegmentService.identify_reportable_segments(sample_segments)
        # Segment 1 has revenue 5B, profit 800M, assets 3B -> all > 10% threshold
        # Segment 2 has revenue 300M, profit 50M, assets 200M -> likely not reportable
        assert reportable == [sample_segments[0]]
        assert sample_segments[0].is_reportable is True
        assert sample_segments[1].is_reportable is False

    def test_can_aggregate_same_type(self, sample_segments):
        # Both are BUSINESS type
        assert PSAK5SegmentService.can_aggregate(
            sample_segments, [PSAK5AggregationCriteria.SIMILAR_ECONOMIC_CHARACTERISTICS]
        ) is True

    def test_can_aggregate_different_types(self):
        seg1 = PSAK5Segment(
            segment_id=uuid4(),
            segment_name="A",
            segment_type=PSAK5SegmentType.BUSINESS,
        )
        seg2 = PSAK5Segment(
            segment_id=uuid4(),
            segment_name="B",
            segment_type=PSAK5SegmentType.GEOGRAPHICAL,
        )
        assert PSAK5SegmentService.can_aggregate(
            [seg1, seg2], [PSAK5AggregationCriteria.SIMILAR_PRODUCTS]
        ) is False

    def test_can_aggregate_single_segment(self, sample_segment):
        assert PSAK5SegmentService.can_aggregate(
            [sample_segment], [PSAK5AggregationCriteria.SIMILAR_PRODUCTS]
        ) is True

    def test_compute_segment_reconciliation(self, sample_disclosure):
        total_entity_revenue = Decimal("6000000000")
        total_entity_profit = Decimal("850000000")
        total_entity_assets = Decimal("3200000000")

        rec = PSAK5SegmentService.compute_segment_reconciliation(
            sample_disclosure.segments,
            total_entity_revenue,
            total_entity_profit,
            total_entity_assets,
        )
        # Both segments are reportable by default
        total_segment_revenue = Decimal("6000000000") + Decimal("300000000")  # 6.3B
        total_segment_profit = Decimal("800000000") + Decimal("50000000")  # 850M
        total_segment_assets = Decimal("3000000000") + Decimal("200000000")  # 3.2B

        assert "Total segmen" in rec["revenue"]
        assert str(total_entity_revenue) in rec["revenue"]
        assert "Total segmen" in rec["profit_loss"]
        assert "Total segmen" in rec["assets"]


# ============================================================================
# Tests for PSAK5Rules
# ============================================================================

class TestPSAK5Rules:
    def test_validate_reportable_segments_valid(self, sample_segments):
        # Mark all as reportable
        for seg in sample_segments:
            seg.is_reportable = True
        result = PSAK5Rules.validate_reportable_segments(sample_segments)
        assert result.is_compliant is True
        assert result.compliance_level == PSAK5ComplianceLevel.FULL

    def test_validate_reportable_segments_no_reportable(self, sample_segments):
        for seg in sample_segments:
            seg.is_reportable = False
        result = PSAK5Rules.validate_reportable_segments(sample_segments)
        assert result.is_compliant is False
        assert "Tidak ada segmen yang memenuhi threshold 10%" in result.errors

    def test_validate_reportable_segments_less_than_75_percent(self, sample_segments):
        # Make only small segment reportable
        for seg in sample_segments:
            seg.is_reportable = False
        sample_segments[1].is_reportable = True
        result = PSAK5Rules.validate_reportable_segments(sample_segments)
        # total external of reportable = 300M, total entity = 5.3B -> ~5.6% < 75%
        assert result.is_compliant is True  # only warning, not error
        assert "kurang dari 75%" in result.warnings[0]

    def test_validate_entity_wide_disclosures_all_present(self, sample_segments):
        result = PSAK5Rules.validate_entity_wide_disclosures(
            sample_segments,
            has_product_disclosure=True,
            has_geographic_disclosure=True,
            has_major_customer_disclosure=True,
        )
        assert result.is_compliant is True
        assert result.compliance_level == PSAK5ComplianceLevel.FULL

    def test_validate_entity_wide_disclosures_missing_product(self, sample_segments):
        result = PSAK5Rules.validate_entity_wide_disclosures(
            sample_segments,
            has_product_disclosure=False,
            has_geographic_disclosure=True,
            has_major_customer_disclosure=True,
        )
        assert result.is_compliant is False
        assert "Pengungkapan pendapatan per produk/jasa tidak disajikan" in result.errors

    def test_validate_entity_wide_disclosures_missing_geo(self, sample_segments):
        result = PSAK5Rules.validate_entity_wide_disclosures(
            sample_segments,
            has_product_disclosure=True,
            has_geographic_disclosure=False,
            has_major_customer_disclosure=True,
        )
        assert result.is_compliant is False
        assert "Pengungkapan pendapatan per area geografis tidak disajikan" in result.errors

    def test_validate_entity_wide_disclosures_missing_major_customer(self, sample_segments):
        result = PSAK5Rules.validate_entity_wide_disclosures(
            sample_segments,
            has_product_disclosure=True,
            has_geographic_disclosure=True,
            has_major_customer_disclosure=False,
        )
        assert result.is_compliant is True  # only warning
        assert "Tidak ada pengungkapan pelanggan utama" in result.warnings[0]


# ============================================================================
# Tests for PSAK5Validator
# ============================================================================

class TestPSAK5Validator:
    def test_create_segment(self, validator):
        seg = validator.create_segment(
            segment_name="Test Segment",
            segment_type=PSAK5SegmentType.BUSINESS,
            revenue_external=Decimal("1000000"),
            profit_loss=Decimal("100000"),
            assets=Decimal("500000"),
        )
        assert isinstance(seg, PSAK5Segment)
        assert seg.segment_name == "Test Segment"
        assert seg.total_revenue == Decimal("1000000")

    def test_create_disclosure(self, validator, sample_segments):
        entity_id = uuid4()
        disclosure = validator.create_disclosure(
            entity_id=entity_id,
            entity_name="Test Entity",
            reporting_period_end=datetime(2026, 12, 31, tzinfo=UTC),
            segments=sample_segments,
        )
        assert isinstance(disclosure, PSAK5SegmentDisclosure)
        assert disclosure.entity_id == entity_id
        assert len(disclosure.segments) == 2

    def test_identify_reportable_segments(self, validator, sample_disclosure):
        # Reset reportable flags
        for seg in sample_disclosure.segments:
            seg.is_reportable = False
        new_disclosure = validator.identify_reportable_segments(sample_disclosure)
        # Should identify segment 0 as reportable
        assert new_disclosure.segments[0].is_reportable is True
        assert new_disclosure.segments[1].is_reportable is False

    def test_compute_reconciliations(self, validator, sample_disclosure):
        total_entity_revenue = Decimal("6000000000")
        total_entity_profit = Decimal("850000000")
        total_entity_assets = Decimal("3200000000")

        new_disclosure = validator.compute_reconciliations(
            sample_disclosure,
            total_entity_revenue,
            total_entity_profit,
            total_entity_assets,
        )
        assert new_disclosure.reconciliation_revenue is not None
        assert "Total segmen" in new_disclosure.reconciliation_revenue
        assert new_disclosure.reconciliation_profit_loss is not None
        assert new_disclosure.reconciliation_assets is not None

    def test_validate_disclosure_valid(self, validator, sample_disclosure):
        # Make sure all segments are reportable
        for seg in sample_disclosure.segments:
            seg.is_reportable = True
        result = validator.validate_disclosure(sample_disclosure)
        assert result.is_compliant is True
        assert result.compliance_level == PSAK5ComplianceLevel.FULL

    def test_validate_disclosure_with_errors(self, validator, sample_disclosure):
        # Make no segments reportable
        for seg in sample_disclosure.segments:
            seg.is_reportable = False
        # Also remove entity-wide disclosures
        sample_disclosure.entity_wide_disclosures = {}
        result = validator.validate_disclosure(sample_disclosure)
        assert result.is_compliant is False
        assert len(result.errors) > 0
        assert "Tidak ada segmen yang memenuhi threshold 10%" in result.errors

    def test_add_segment(self, validator, sample_disclosure):
        new_seg = PSAK5Segment(
            segment_id=uuid4(),
            segment_name="New Segment",
            segment_type=PSAK5SegmentType.BUSINESS,
        )
        new_disclosure = validator.add_segment(sample_disclosure, new_seg)
        assert len(new_disclosure.segments) == len(sample_disclosure.segments) + 1
        assert new_disclosure.segments[-1] is new_seg

    def test_merge_results(self, validator):
        main = PSAK5ValidationResult(
            is_compliant=True,
            compliance_level=PSAK5ComplianceLevel.FULL,
        )
        other = PSAK5ValidationResult(
            is_compliant=False,
            compliance_level=PSAK5ComplianceLevel.NON_COMPLIANT,
            errors=["e1"],
            warnings=["w1"],
        )
        merged = validator._merge_results(main, other)
        assert merged.is_compliant is False
        assert merged.compliance_level == PSAK5ComplianceLevel.NON_COMPLIANT
        assert len(merged.errors) == 1
        assert len(merged.warnings) == 1

    def test_get_requirements_summary(self, validator):
        summary = validator.get_requirements_summary()
        assert "threshold" in summary
        assert "minimum_coverage" in summary
        assert "entity_wide_disclosures" in summary
        assert len(summary["entity_wide_disclosures"]) == 3


# ============================================================================
# Tests for Singleton Accessor
# ============================================================================

def test_get_psak5_validator():
    v1 = get_psak5_validator()
    v2 = get_psak5_validator()
    assert v1 is v2
    assert isinstance(v1, PSAK5Validator)