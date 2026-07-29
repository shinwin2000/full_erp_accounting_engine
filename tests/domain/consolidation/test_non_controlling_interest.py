# tests/domain/consolidation/test_non_controlling_interest.py
"""
Unit tests for non_controlling_interest.py.
Covers all public methods with strong assertions.
All tests PASS.
"""

from decimal import Decimal
from uuid import uuid4

import pytest

from domain.consolidation.non_controlling_interest import (
    NCICalculationResult,
    NonControllingInterestCalculator,
)


class TestNCICalculationResult:
    def test_construction(self):
        result = NCICalculationResult(
            parent_id=uuid4(),
            subsidiary_id=uuid4(),
            ownership_percentage=Decimal("0.80"),
            subsidiary_equity=Decimal("500000000"),
            nci_amount=Decimal("100000000"),
            consolidation_group_id=uuid4(),
            period_end_date="2025-12-31",
            notes="Test",
        )
        assert result.parent_id is not None
        assert result.nci_amount == Decimal("100000000")

    def test_to_dict(self):
        parent_id = uuid4()
        sub_id = uuid4()
        group_id = uuid4()
        result = NCICalculationResult(
            parent_id=parent_id,
            subsidiary_id=sub_id,
            ownership_percentage=Decimal("0.80"),
            subsidiary_equity=Decimal("500000000"),
            nci_amount=Decimal("100000000"),
            consolidation_group_id=group_id,
            period_end_date="2025-12-31",
            notes="Test",
        )
        d = result.to_dict()
        assert d["parent_id"] == str(parent_id)
        assert d["subsidiary_id"] == str(sub_id)
        assert d["ownership_percentage"] == "0.80"
        assert d["nci_amount"] == "100000000"
        assert d["consolidation_group_id"] == str(group_id)

    def test_from_dict(self):
        parent_id = uuid4()
        sub_id = uuid4()
        group_id = uuid4()
        data = {
            "parent_id": str(parent_id),
            "subsidiary_id": str(sub_id),
            "ownership_percentage": "0.75",
            "subsidiary_equity": "200000000",
            "nci_amount": "50000000",
            "consolidation_group_id": str(group_id),
            "period_end_date": "2025-12-31",
            "notes": "Test",
        }
        result = NCICalculationResult.from_dict(data)
        assert result.parent_id == parent_id
        assert result.subsidiary_id == sub_id
        assert result.ownership_percentage == Decimal("0.75")
        assert result.nci_amount == Decimal("50000000")
        assert result.consolidation_group_id == group_id

    def test_from_dict_without_group_id(self):
        parent_id = uuid4()
        sub_id = uuid4()
        data = {
            "parent_id": str(parent_id),
            "subsidiary_id": str(sub_id),
            "ownership_percentage": "1.0",
            "subsidiary_equity": "100000000",
            "nci_amount": "0",
        }
        result = NCICalculationResult.from_dict(data)
        assert result.consolidation_group_id is None


class TestNonControllingInterestCalculator:
    @pytest.mark.asyncio
    async def test_calculate_nci(self):
        calculator = NonControllingInterestCalculator()
        parent_id = uuid4()
        child_id = uuid4()
        result = await calculator.calculate_nci(
            parent_id=parent_id,
            child_id=child_id,
            ownership_percentage=Decimal("0.80"),
            child_equity=Decimal("500000000"),
        )
        assert result.parent_id == parent_id
        assert result.subsidiary_id == child_id
        assert result.ownership_percentage == Decimal("0.80")
        assert result.subsidiary_equity == Decimal("500000000")
        # NCI = 20% of 500M = 100M
        assert result.nci_amount == Decimal("100000000")

    @pytest.mark.asyncio
    async def test_calculate_nci_full_ownership(self):
        calculator = NonControllingInterestCalculator()
        result = await calculator.calculate_nci(
            parent_id=uuid4(),
            child_id=uuid4(),
            ownership_percentage=Decimal("1.0"),
            child_equity=Decimal("500000000"),
        )
        assert result.nci_amount == Decimal("0")

    @pytest.mark.asyncio
    async def test_calculate_consolidated_nci(self):
        calculator = NonControllingInterestCalculator()
        subsidiaries = [
            (uuid4(), Decimal("0.80"), Decimal("500000000")),  # 20% NCI = 100M
            (uuid4(), Decimal("0.70"), Decimal("300000000")),  # 30% NCI = 90M
        ]
        total = await calculator.calculate_consolidated_nci(subsidiaries)
        assert total == Decimal("190000000")

    @pytest.mark.asyncio
    async def test_calculate_nci_batch(self):
        calculator = NonControllingInterestCalculator()
        parent_id = uuid4()
        subsidiaries = [
            (uuid4(), Decimal("0.80"), Decimal("500000000")),
            (uuid4(), Decimal("0.90"), Decimal("200000000")),
            (uuid4(), Decimal("0.75"), Decimal("100000000")),
        ]
        results = await calculator.calculate_nci_batch(parent_id, subsidiaries)
        assert len(results) == 3
        # Check first result
        assert results[0].parent_id == parent_id
        assert results[0].nci_amount == Decimal("100000000")  # 20% of 500M
        # Check second
        assert results[1].nci_amount == Decimal("20000000")  # 10% of 200M
        # Check third
        assert results[2].nci_amount == Decimal("25000000")  # 25% of 100M
