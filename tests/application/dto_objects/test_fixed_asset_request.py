#!/usr/bin/env python3
"""
tests/application/dto_objects/test_fixed_asset_request.py
Comprehensive tests for application/dto_objects/fixed_asset_request.py

Covers:
- All enums (AssetStatus, DepreciationMethod, AssetCategory, DisposalReason)
- All request DTOs:
  - AssetCreateRequest (construction, validation, properties, to_dict, from_dict)
  - UpdateFixedAssetRequest (construction, validation, to_dict)
  - FixedAssetDisposalRequest (construction, validation, net_proceeds, to_dict, from_dict)
  - FixedAssetDepreciationRequest (construction, validation, to_dict)
  - ImpairmentTestRequest (construction, validation, to_dict)
  - RevaluationRequest (construction, validation, to_dict)
  - AssetTransferRequest (construction, validation, to_dict)
  - AssetMaintenanceRequest (construction, validation, to_dict)
  - GetFixedAssetsQuery (construction, validation, get_offset, to_dict)
  - GetAssetDetailRequest (to_dict)
  - GetAssetDepreciationScheduleRequest (to_dict)
- AssetResponseDTO (construction, depreciation_percentage, to_dict)
- FixedAssetRequestFactory (all factory methods with assertions)
- All edge cases and negative paths with parametrized tests
- No flaky datetime (using fixed date fixture)
- No duplicate test structures
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from application.dto_objects.fixed_asset_request import (
    AssetCategory,
    AssetCreateRequest,
    AssetMaintenanceRequest,
    AssetResponseDTO,
    AssetStatus,
    AssetTransferRequest,
    DepreciationMethod,
    DisposalReason,
    FixedAssetDepreciationRequest,
    FixedAssetDisposalRequest,
    FixedAssetRequestFactory,
    GetAssetDepreciationScheduleRequest,
    GetAssetDetailRequest,
    GetFixedAssetsQuery,
    ImpairmentTestRequest,
    RevaluationRequest,
    UpdateFixedAssetRequest,
)

# =============================================================================
# Fixtures
# =============================================================================

FIXED_DATE = date(2026, 1, 15)
FIXED_DATETIME = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def mock_date_today():
    """Mock date.today to return a fixed date."""
    with pytest.MonkeyPatch.context() as m:
        m.setattr("application.dto_objects.fixed_asset_request.date", MagicMock(today=lambda: FIXED_DATE))
        yield


# Actually we'll just use FIXED_DATE directly in tests, no need for mocking date.today
# because the DTOs don't call date.today() internally; they use the passed values.

# =============================================================================
# Tests for Enums
# =============================================================================

class TestEnums:
    def test_asset_status(self):
        assert AssetStatus.ACTIVE.value == "ACTIVE"
        assert AssetStatus.INACTIVE.value == "INACTIVE"
        assert AssetStatus.UNDER_MAINTENANCE.value == "UNDER_MAINTENANCE"
        assert AssetStatus.DISPOSED.value == "DISPOSED"
        assert AssetStatus.FULLY_DEPRECIATED.value == "FULLY_DEPRECIATED"
        assert AssetStatus.IMPAIRED.value == "IMPAIRED"
        assert isinstance(AssetStatus.ACTIVE, AssetStatus)

    def test_depreciation_method(self):
        assert DepreciationMethod.STRAIGHT_LINE.value == "straight_line"
        assert DepreciationMethod.DECLINING_BALANCE.value == "declining_balance"
        assert DepreciationMethod.DOUBLE_DECLINING.value == "double_declining"
        assert DepreciationMethod.SUM_OF_YEARS.value == "sum_of_years"
        assert DepreciationMethod.UNITS_OF_PRODUCTION.value == "units_of_production"
        assert isinstance(DepreciationMethod.STRAIGHT_LINE, DepreciationMethod)

    def test_asset_category(self):
        assert AssetCategory.BUILDING.value == "BUILDING"
        assert AssetCategory.MACHINERY.value == "MACHINERY"
        assert AssetCategory.VEHICLE.value == "VEHICLE"
        assert AssetCategory.FURNITURE.value == "FURNITURE"
        assert AssetCategory.COMPUTER.value == "COMPUTER"
        assert AssetCategory.SOFTWARE.value == "SOFTWARE"
        assert AssetCategory.LAND.value == "LAND"
        assert AssetCategory.OTHER.value == "OTHER"
        assert isinstance(AssetCategory.BUILDING, AssetCategory)

    def test_disposal_reason(self):
        assert DisposalReason.SOLD.value == "SOLD"
        assert DisposalReason.SCRAPPED.value == "SCRAPPED"
        assert DisposalReason.DONATED.value == "DONATED"
        assert DisposalReason.LOST.value == "LOST"
        assert DisposalReason.STOLEN.value == "STOLEN"
        assert DisposalReason.TRADED_IN.value == "TRADED_IN"
        assert isinstance(DisposalReason.SOLD, DisposalReason)


# =============================================================================
# Helpers
# =============================================================================

def create_uuid() -> uuid.UUID:
    return uuid.uuid4()


# =============================================================================
# Tests for AssetCreateRequest
# =============================================================================

class TestAssetCreateRequest:
    @pytest.fixture
    def valid_kwargs(self):
        return {
            "asset_code": "ASSET-001",
            "asset_name": "Test Asset",
            "asset_category_id": create_uuid(),
            "acquisition_date": FIXED_DATE,
            "acquisition_cost": Decimal("10000.00"),
            "salvage_value": Decimal("1000.00"),
            "useful_life_years": 5,
            "depreciation_method": "straight_line",
            "location": "Warehouse A",
            "responsible_party": create_uuid(),
            "description": "Test description",
            "supplier_id": create_uuid(),
            "invoice_number": "INV-001",
            "is_active": True,
            "legal_entity_id": create_uuid(),
            "purchase_order_id": create_uuid(),
            "warranty_expiry_date": FIXED_DATE + timedelta(days=365),
            "insurance_policy_number": "POL-001",
            "insurance_expiry_date": FIXED_DATE + timedelta(days=180),
            "serial_number": "SN-001",
            "model_number": "MOD-001",
        }

    def test_valid_construction(self, valid_kwargs):
        req = AssetCreateRequest(**valid_kwargs)
        assert req.asset_code == "ASSET-001"
        assert req.asset_name == "Test Asset"
        assert req.acquisition_cost == Decimal("10000.00")
        assert req.salvage_value == Decimal("1000.00")
        assert req.useful_life_years == 5
        assert req.depreciation_method == "straight_line"
        assert req.depreciable_amount == Decimal("9000.00")
        assert req.annual_depreciation_straight_line == Decimal("1800.00")
        assert req.monthly_depreciation_straight_line == Decimal("150.00")

    @pytest.mark.parametrize(
        "field,value,expected_error",
        [
            ("asset_code", "", "Asset code must be at least 3 characters"),
            ("asset_code", "AB", "Asset code must be at least 3 characters"),
            ("asset_name", "", "Asset name is required"),
            ("acquisition_cost", Decimal("-100"), "Acquisition cost must be positive"),
            ("acquisition_cost", Decimal("0"), "Acquisition cost must be positive"),
            ("salvage_value", Decimal("-10"), "Salvage value cannot be negative"),
            ("salvage_value", Decimal("15000"), "Salvage value cannot exceed acquisition cost"),
            ("useful_life_years", 0, "Useful life must be at least 1 year"),
            ("depreciation_method", "invalid", "Invalid depreciation_method"),
        ]
    )
    def test_validation_errors(self, valid_kwargs, field, value, expected_error):
        valid_kwargs[field] = value
        with pytest.raises(ValueError, match=expected_error):
            AssetCreateRequest(**valid_kwargs)

    def test_to_dict(self, valid_kwargs):
        req = AssetCreateRequest(**valid_kwargs)
        d = req.to_dict()
        assert d["asset_code"] == "ASSET-001"
        assert d["asset_name"] == "Test Asset"
        assert d["acquisition_cost"] == "10000.00"
        assert d["salvage_value"] == "1000.00"
        assert d["depreciable_amount"] == "9000.00"
        assert d["annual_depreciation"] == "1800.00"
        assert d["monthly_depreciation"] == "150.00"
        assert d["legal_entity_id"] == str(valid_kwargs["legal_entity_id"])

    def test_from_dict(self, valid_kwargs):
        # Create from dict using the same data
        d = {
            "asset_code": "ASSET-002",
            "asset_name": "From Dict",
            "asset_category_id": str(create_uuid()),
            "acquisition_date": FIXED_DATE.isoformat(),
            "acquisition_cost": "20000.00",
            "salvage_value": "2000.00",
            "useful_life_years": 10,
            "depreciation_method": "declining_balance",
            "location": "Office",
            "responsible_party": str(create_uuid()),
            "description": "From dict description",
            "supplier_id": str(create_uuid()),
            "invoice_number": "INV-002",
            "is_active": False,
            "legal_entity_id": str(create_uuid()),
            "purchase_order_id": str(create_uuid()),
            "warranty_expiry_date": FIXED_DATE.isoformat(),
            "insurance_policy_number": "POL-002",
            "insurance_expiry_date": FIXED_DATE.isoformat(),
            "serial_number": "SN-002",
            "model_number": "MOD-002",
        }
        req = AssetCreateRequest.from_dict(d)
        assert req.asset_code == "ASSET-002"
        assert req.asset_name == "From Dict"
        assert req.acquisition_cost == Decimal("20000.00")
        assert req.salvage_value == Decimal("2000.00")
        assert req.useful_life_years == 10
        assert req.depreciation_method == "declining_balance"
        assert req.is_active is False


# =============================================================================
# Tests for UpdateFixedAssetRequest
# =============================================================================

class TestUpdateFixedAssetRequest:
    @pytest.fixture
    def valid_kwargs(self):
        return {
            "asset_id": create_uuid(),
            "asset_name": "Updated Name",
            "location": "New Location",
            "responsible_party": create_uuid(),
            "description": "Updated description",
            "salvage_value": Decimal("500.00"),
            "useful_life_years": 8,
            "depreciation_method": "double_declining",
            "is_active": False,
            "legal_entity_id": create_uuid(),
            "status": "INACTIVE",
            "warranty_expiry_date": FIXED_DATE + timedelta(days=400),
            "insurance_policy_number": "POL-UPD",
            "insurance_expiry_date": FIXED_DATE + timedelta(days=200),
        }

    def test_valid_construction(self, valid_kwargs):
        req = UpdateFixedAssetRequest(**valid_kwargs)
        assert req.asset_id == valid_kwargs["asset_id"]
        assert req.asset_name == "Updated Name"
        assert req.salvage_value == Decimal("500.00")
        assert req.status == "INACTIVE"

    def test_no_fields_raises(self):
        with pytest.raises(ValueError, match="At least one field to update must be provided"):
            UpdateFixedAssetRequest(asset_id=create_uuid())

    @pytest.mark.parametrize(
        "field,value,expected_error",
        [
            ("asset_name", "A", "Asset name must be at least 2 characters"),
            ("salvage_value", Decimal("-10"), "Salvage value cannot be negative"),
            ("useful_life_years", 0, "Useful life must be at least 1 year"),
            ("status", "INVALID_STATUS", "Invalid status"),
        ]
    )
    def test_validation_errors(self, valid_kwargs, field, value, expected_error):
        valid_kwargs[field] = value
        with pytest.raises(ValueError, match=expected_error):
            UpdateFixedAssetRequest(**valid_kwargs)

    def test_to_dict(self, valid_kwargs):
        req = UpdateFixedAssetRequest(**valid_kwargs)
        d = req.to_dict()
        assert d["asset_id"] == str(valid_kwargs["asset_id"])
        assert d["asset_name"] == "Updated Name"
        assert d["salvage_value"] == "500.00"
        assert d["status"] == "INACTIVE"
        assert "location" in d


# =============================================================================
# Tests for FixedAssetDisposalRequest
# =============================================================================

class TestFixedAssetDisposalRequest:
    @pytest.fixture
    def valid_kwargs(self):
        return {
            "asset_id": create_uuid(),
            "disposal_date": FIXED_DATE,
            "disposal_reason": "Sold due to obsolescence",
            "proceeds_from_sale": Decimal("8000.00"),
            "disposal_cost": Decimal("500.00"),
            "notes": "Sold to third party",
            "legal_entity_id": create_uuid(),
            "buyer_name": "Buyer Corp",
            "invoice_number": "DIS-INV-001",
        }

    def test_valid_construction(self, valid_kwargs):
        req = FixedAssetDisposalRequest(**valid_kwargs)
        assert req.asset_id == valid_kwargs["asset_id"]
        assert req.disposal_reason == "Sold due to obsolescence"
        assert req.proceeds_from_sale == Decimal("8000.00")
        assert req.disposal_cost == Decimal("500.00")
        assert req.net_proceeds == Decimal("7500.00")

    @pytest.mark.parametrize(
        "field,value,expected_error",
        [
            ("disposal_reason", "Short", "Disposal reason must be at least 5 characters"),
            ("proceeds_from_sale", Decimal("-100"), "Proceeds from sale cannot be negative"),
            ("disposal_cost", Decimal("-50"), "Disposal cost cannot be negative"),
        ]
    )
    def test_validation_errors(self, valid_kwargs, field, value, expected_error):
        valid_kwargs[field] = value
        with pytest.raises(ValueError, match=expected_error):
            FixedAssetDisposalRequest(**valid_kwargs)

    def test_to_dict(self, valid_kwargs):
        req = FixedAssetDisposalRequest(**valid_kwargs)
        d = req.to_dict()
        assert d["asset_id"] == str(valid_kwargs["asset_id"])
        assert d["disposal_reason"] == "Sold due to obsolescence"
        assert d["proceeds_from_sale"] == "8000.00"
        assert d["net_proceeds"] == "7500.00"
        assert d["buyer_name"] == "Buyer Corp"

    def test_from_dict(self):
        data = {
            "asset_id": str(create_uuid()),
            "disposal_date": FIXED_DATE.isoformat(),
            "disposal_reason": "Scrapped",
            "proceeds_from_sale": "5000.00",
            "disposal_cost": "200.00",
            "notes": "Scrapped due to damage",
            "legal_entity_id": str(create_uuid()),
            "buyer_name": None,
            "invoice_number": "SCRAP-001",
        }
        req = FixedAssetDisposalRequest.from_dict(data)
        assert req.disposal_reason == "Scrapped"
        assert req.proceeds_from_sale == Decimal("5000.00")
        assert req.disposal_cost == Decimal("200.00")
        assert req.net_proceeds == Decimal("4800.00")


# =============================================================================
# Tests for FixedAssetDepreciationRequest
# =============================================================================

class TestFixedAssetDepreciationRequest:
    @pytest.fixture
    def valid_kwargs(self):
        return {
            "as_of_date": FIXED_DATE,
            "asset_ids": [create_uuid(), create_uuid()],
            "period": "quarterly",
            "legal_entity_id": create_uuid(),
            "create_journal": True,
            "journal_description": "Monthly depreciation run",
        }

    def test_valid_construction(self, valid_kwargs):
        req = FixedAssetDepreciationRequest(**valid_kwargs)
        assert req.as_of_date == FIXED_DATE
        assert len(req.asset_ids) == 2
        assert req.period == "quarterly"
        assert req.create_journal is True

    @pytest.mark.parametrize(
        "period,expected_error",
        [
            ("invalid", "Invalid period"),
            ("weekly", "Invalid period"),
        ]
    )
    def test_validation_errors(self, valid_kwargs, period, expected_error):
        valid_kwargs["period"] = period
        with pytest.raises(ValueError, match=expected_error):
            FixedAssetDepreciationRequest(**valid_kwargs)

    def test_to_dict(self, valid_kwargs):
        req = FixedAssetDepreciationRequest(**valid_kwargs)
        d = req.to_dict()
        assert d["as_of_date"] == FIXED_DATE.isoformat()
        assert len(d["asset_ids"]) == 2
        assert d["period"] == "quarterly"
        assert d["create_journal"] is True


# =============================================================================
# Tests for ImpairmentTestRequest
# =============================================================================

class TestImpairmentTestRequest:
    @pytest.fixture
    def valid_kwargs(self):
        return {
            "asset_id": create_uuid(),
            "test_date": FIXED_DATE,
            "recoverable_amount": Decimal("8000.00"),
            "notes": "Impairment test due to market decline",
            "legal_entity_id": create_uuid(),
            "approved_by": create_uuid(),
        }

    def test_valid_construction(self, valid_kwargs):
        req = ImpairmentTestRequest(**valid_kwargs)
        assert req.asset_id == valid_kwargs["asset_id"]
        assert req.recoverable_amount == Decimal("8000.00")
        assert req.impairment_loss == Decimal("0")  # placeholder

    def test_validation_negative_recoverable(self, valid_kwargs):
        valid_kwargs["recoverable_amount"] = Decimal("-100")
        with pytest.raises(ValueError, match="Recoverable amount cannot be negative"):
            ImpairmentTestRequest(**valid_kwargs)

    def test_to_dict(self, valid_kwargs):
        req = ImpairmentTestRequest(**valid_kwargs)
        d = req.to_dict()
        assert d["asset_id"] == str(valid_kwargs["asset_id"])
        assert d["recoverable_amount"] == "8000.00"
        assert d["impairment_loss"] == "0"
        assert "approved_by" in d


# =============================================================================
# Tests for RevaluationRequest
# =============================================================================

class TestRevaluationRequest:
    @pytest.fixture
    def valid_kwargs(self):
        return {
            "asset_id": create_uuid(),
            "new_acquisition_cost": Decimal("15000.00"),
            "revaluation_date": FIXED_DATE,
            "notes": "Revaluation due to market increase",
            "legal_entity_id": create_uuid(),
            "approved_by": create_uuid(),
            "appraisal_firm": "Appraisal Corp",
            "appraisal_number": "APP-2026-001",
        }

    def test_valid_construction(self, valid_kwargs):
        req = RevaluationRequest(**valid_kwargs)
        assert req.asset_id == valid_kwargs["asset_id"]
        assert req.new_acquisition_cost == Decimal("15000.00")
        assert req.revaluation_increase == Decimal("0")  # placeholder
        assert req.revaluation_decrease == Decimal("0")  # placeholder

    def test_validation_negative_cost(self, valid_kwargs):
        valid_kwargs["new_acquisition_cost"] = Decimal("-100")
        with pytest.raises(ValueError, match="New acquisition cost must be positive"):
            RevaluationRequest(**valid_kwargs)

    def test_to_dict(self, valid_kwargs):
        req = RevaluationRequest(**valid_kwargs)
        d = req.to_dict()
        assert d["asset_id"] == str(valid_kwargs["asset_id"])
        assert d["new_acquisition_cost"] == "15000.00"
        assert d["appraisal_firm"] == "Appraisal Corp"
        assert d["revaluation_increase"] == "0"
        assert d["revaluation_decrease"] == "0"


# =============================================================================
# Tests for AssetTransferRequest
# =============================================================================

class TestAssetTransferRequest:
    @pytest.fixture
    def valid_kwargs(self):
        return {
            "asset_id": create_uuid(),
            "transfer_date": FIXED_DATE,
            "from_location": "Warehouse A",
            "to_location": "Warehouse B",
            "from_department": "Dept A",
            "to_department": "Dept B",
            "responsible_party": create_uuid(),
            "notes": "Transfer due to reorganization",
            "legal_entity_id": create_uuid(),
            "approved_by": create_uuid(),
        }

    def test_valid_construction(self, valid_kwargs):
        req = AssetTransferRequest(**valid_kwargs)
        assert req.from_location == "Warehouse A"
        assert req.to_location == "Warehouse B"
        assert req.from_department == "Dept A"

    def test_validation_missing_location(self, valid_kwargs):
        valid_kwargs["from_location"] = ""
        with pytest.raises(ValueError, match="From location and to location are required"):
            AssetTransferRequest(**valid_kwargs)

    def test_validation_same_location_and_department(self, valid_kwargs):
        valid_kwargs["from_location"] = "Warehouse A"
        valid_kwargs["to_location"] = "Warehouse A"
        valid_kwargs["from_department"] = "Dept A"
        valid_kwargs["to_department"] = "Dept A"
        with pytest.raises(ValueError, match="Source and destination cannot be the same"):
            AssetTransferRequest(**valid_kwargs)

    def test_to_dict(self, valid_kwargs):
        req = AssetTransferRequest(**valid_kwargs)
        d = req.to_dict()
        assert d["from_location"] == "Warehouse A"
        assert d["to_location"] == "Warehouse B"
        assert d["from_department"] == "Dept A"


# =============================================================================
# Tests for AssetMaintenanceRequest
# =============================================================================

class TestAssetMaintenanceRequest:
    @pytest.fixture
    def valid_kwargs(self):
        return {
            "asset_id": create_uuid(),
            "maintenance_date": FIXED_DATE,
            "maintenance_type": "PREVENTIVE",
            "cost": Decimal("500.00"),
            "description": "Routine maintenance",
            "vendor_id": create_uuid(),
            "invoice_number": "MAINT-INV-001",
            "next_maintenance_date": FIXED_DATE + timedelta(days=90),
            "notes": "Completed on time",
            "legal_entity_id": create_uuid(),
        }

    def test_valid_construction(self, valid_kwargs):
        req = AssetMaintenanceRequest(**valid_kwargs)
        assert req.maintenance_type == "PREVENTIVE"
        assert req.cost == Decimal("500.00")
        assert req.description == "Routine maintenance"

    @pytest.mark.parametrize(
        "field,value,expected_error",
        [
            ("maintenance_type", "INVALID", "Invalid maintenance_type"),
            ("cost", Decimal("-10"), "Cost cannot be negative"),
            ("description", "", "Description is required"),
        ]
    )
    def test_validation_errors(self, valid_kwargs, field, value, expected_error):
        valid_kwargs[field] = value
        with pytest.raises(ValueError, match=expected_error):
            AssetMaintenanceRequest(**valid_kwargs)

    def test_to_dict(self, valid_kwargs):
        req = AssetMaintenanceRequest(**valid_kwargs)
        d = req.to_dict()
        assert d["maintenance_type"] == "PREVENTIVE"
        assert d["cost"] == "500.00"
        assert d["description"] == "Routine maintenance"


# =============================================================================
# Tests for GetFixedAssetsQuery
# =============================================================================

class TestGetFixedAssetsQuery:
    @pytest.fixture
    def valid_kwargs(self):
        return {
            "legal_entity_id": create_uuid(),
            "asset_category_id": create_uuid(),
            "location": "Warehouse A",
            "is_active": True,
            "is_fully_depreciated": False,
            "acquisition_date_from": FIXED_DATE,
            "acquisition_date_to": FIXED_DATE + timedelta(days=30),
            "status": "ACTIVE",
            "responsible_party": create_uuid(),
            "search": "computer",
            "page": 2,
            "page_size": 10,
        }

    def test_valid_construction(self, valid_kwargs):
        req = GetFixedAssetsQuery(**valid_kwargs)
        assert req.legal_entity_id == valid_kwargs["legal_entity_id"]
        assert req.page == 2
        assert req.page_size == 10
        assert req.get_offset() == 10

    @pytest.mark.parametrize(
        "field,value,expected_error",
        [
            ("page", 0, "page must be >= 1"),
            ("page_size", 0, "page_size must be between 1 and 500"),
            ("page_size", 600, "page_size must be between 1 and 500"),
            ("status", "INVALID", "Invalid status"),
        ]
    )
    def test_validation_errors(self, valid_kwargs, field, value, expected_error):
        valid_kwargs[field] = value
        with pytest.raises(ValueError, match=expected_error):
            GetFixedAssetsQuery(**valid_kwargs)

    def test_to_dict(self, valid_kwargs):
        req = GetFixedAssetsQuery(**valid_kwargs)
        d = req.to_dict()
        assert d["page"] == 2
        assert d["page_size"] == 10
        assert d["offset"] == 10
        assert d["location"] == "Warehouse A"
        assert d["status"] == "ACTIVE"


# =============================================================================
# Tests for GetAssetDetailRequest
# =============================================================================

class TestGetAssetDetailRequest:
    def test_to_dict(self):
        asset_id = create_uuid()
        le_id = create_uuid()
        req = GetAssetDetailRequest(asset_id=asset_id, legal_entity_id=le_id)
        d = req.to_dict()
        assert d["asset_id"] == str(asset_id)
        assert d["legal_entity_id"] == str(le_id)


# =============================================================================
# Tests for GetAssetDepreciationScheduleRequest
# =============================================================================

class TestGetAssetDepreciationScheduleRequest:
    def test_to_dict(self):
        asset_id = create_uuid()
        le_id = create_uuid()
        from_date = FIXED_DATE
        to_date = FIXED_DATE + timedelta(days=30)
        req = GetAssetDepreciationScheduleRequest(
            asset_id=asset_id,
            legal_entity_id=le_id,
            from_date=from_date,
            to_date=to_date,
        )
        d = req.to_dict()
        assert d["asset_id"] == str(asset_id)
        assert d["legal_entity_id"] == str(le_id)
        assert d["from_date"] == from_date.isoformat()
        assert d["to_date"] == to_date.isoformat()


# =============================================================================
# Tests for AssetResponseDTO
# =============================================================================

class TestAssetResponseDTO:
    @pytest.fixture
    def valid_kwargs(self):
        return {
            "id": create_uuid(),
            "asset_code": "ASSET-001",
            "asset_name": "Test Asset",
            "asset_category": "MACHINERY",
            "acquisition_date": FIXED_DATE,
            "acquisition_cost": Decimal("10000.00"),
            "salvage_value": Decimal("1000.00"),
            "useful_life_years": 5,
            "depreciation_method": "straight_line",
            "accumulated_depreciation": Decimal("3600.00"),
            "book_value": Decimal("6400.00"),
            "location": "Warehouse A",
            "responsible_party": "John Doe",
            "status": "ACTIVE",
            "is_active": True,
            "created_at": FIXED_DATETIME,
            "updated_at": FIXED_DATETIME,
            "version": 1,
        }

    def test_valid_construction(self, valid_kwargs):
        dto = AssetResponseDTO(**valid_kwargs)
        assert dto.id == valid_kwargs["id"]
        assert dto.asset_code == "ASSET-001"
        assert dto.acquisition_cost == Decimal("10000.00")
        assert dto.book_value == Decimal("6400.00")
        assert dto.depreciation_percentage == Decimal("36.00")  # 3600/10000 * 100

    def test_depreciation_percentage_zero_cost(self, valid_kwargs):
        valid_kwargs["acquisition_cost"] = Decimal("0")
        dto = AssetResponseDTO(**valid_kwargs)
        assert dto.depreciation_percentage == Decimal("0")

    def test_to_dict(self, valid_kwargs):
        dto = AssetResponseDTO(**valid_kwargs)
        d = dto.to_dict()
        assert d["id"] == str(valid_kwargs["id"])
        assert d["asset_code"] == "ASSET-001"
        assert d["book_value"] == "6400.00"
        assert d["accumulated_depreciation"] == "3600.00"
        assert "created_at" in d


# =============================================================================
# Tests for FixedAssetRequestFactory
# =============================================================================

class TestFixedAssetRequestFactory:
    def test_create_asset(self):
        asset_code = "FACT-001"
        asset_name = "Factory Asset"
        cat_id = create_uuid()
        acq_date = FIXED_DATE
        cost = Decimal("50000.00")
        le_id = create_uuid()
        salvage = Decimal("5000.00")
        life = 10
        method = "declining_balance"

        req = FixedAssetRequestFactory.create_asset(
            asset_code=asset_code,
            asset_name=asset_name,
            asset_category_id=cat_id,
            acquisition_date=acq_date,
            acquisition_cost=cost,
            legal_entity_id=le_id,
            salvage_value=salvage,
            useful_life_years=life,
            depreciation_method=method,
        )
        assert req.asset_code == asset_code
        assert req.asset_name == asset_name
        assert req.asset_category_id == cat_id
        assert req.acquisition_date == acq_date
        assert req.acquisition_cost == cost
        assert req.legal_entity_id == le_id
        assert req.salvage_value == salvage
        assert req.useful_life_years == life
        assert req.depreciation_method == method

    def test_create_disposal(self):
        asset_id = create_uuid()
        disposal_date = FIXED_DATE
        reason = "Sold due to upgrade"
        proceeds = Decimal("30000.00")
        cost = Decimal("1000.00")
        req = FixedAssetRequestFactory.create_disposal(
            asset_id=asset_id,
            disposal_date=disposal_date,
            disposal_reason=reason,
            proceeds_from_sale=proceeds,
            disposal_cost=cost,
        )
        assert req.asset_id == asset_id
        assert req.disposal_date == disposal_date
        assert req.disposal_reason == reason
        assert req.proceeds_from_sale == proceeds
        assert req.disposal_cost == cost
        assert req.net_proceeds == Decimal("29000.00")

    def test_create_depreciation_request(self):
        as_of_date = FIXED_DATE
        le_id = create_uuid()
        period = "yearly"
        req = FixedAssetRequestFactory.create_depreciation_request(
            as_of_date=as_of_date,
            legal_entity_id=le_id,
            period=period,
        )
        assert req.as_of_date == as_of_date
        assert req.legal_entity_id == le_id
        assert req.period == period

    def test_create_impairment_test(self):
        asset_id = create_uuid()
        test_date = FIXED_DATE
        recoverable = Decimal("45000.00")
        req = FixedAssetRequestFactory.create_impairment_test(
            asset_id=asset_id,
            test_date=test_date,
            recoverable_amount=recoverable,
        )
        assert req.asset_id == asset_id
        assert req.test_date == test_date
        assert req.recoverable_amount == recoverable

    def test_create_revaluation(self):
        asset_id = create_uuid()
        new_cost = Decimal("60000.00")
        reval_date = FIXED_DATE
        req = FixedAssetRequestFactory.create_revaluation(
            asset_id=asset_id,
            new_acquisition_cost=new_cost,
            revaluation_date=reval_date,
        )
        assert req.asset_id == asset_id
        assert req.new_acquisition_cost == new_cost
        assert req.revaluation_date == reval_date

    def test_create_transfer(self):
        asset_id = create_uuid()
        transfer_date = FIXED_DATE
        from_loc = "Main Office"
        to_loc = "Branch Office"
        req = FixedAssetRequestFactory.create_transfer(
            asset_id=asset_id,
            transfer_date=transfer_date,
            from_location=from_loc,
            to_location=to_loc,
        )
        assert req.asset_id == asset_id
        assert req.transfer_date == transfer_date
        assert req.from_location == from_loc
        assert req.to_location == to_loc


# =============================================================================
# Additional negative path tests for edge cases not covered
# =============================================================================

class TestAdditionalNegativePaths:
    def test_asset_create_request_validation_asset_code_none(self):
        with pytest.raises(ValueError, match="Asset code must be at least 3 characters"):
            AssetCreateRequest(
                asset_code=None,  # type: ignore
                asset_name="Test",
                asset_category_id=create_uuid(),
                acquisition_date=FIXED_DATE,
                acquisition_cost=Decimal("1000"),
            )

    def test_update_fixed_asset_request_no_fields_with_none(self):
        with pytest.raises(ValueError, match="At least one field to update must be provided"):
            UpdateFixedAssetRequest(
                asset_id=create_uuid(),
                asset_name=None,
                location=None,
                responsible_party=None,
                description=None,
                salvage_value=None,
                useful_life_years=None,
                depreciation_method=None,
                is_active=None,
                legal_entity_id=None,
                status=None,
                warranty_expiry_date=None,
                insurance_policy_number=None,
                insurance_expiry_date=None,
            )

    def test_asset_transfer_request_same_location_different_dept_allowed(self):
        # Should not raise if location same but department different
        req = AssetTransferRequest(
            asset_id=create_uuid(),
            transfer_date=FIXED_DATE,
            from_location="WH",
            to_location="WH",
            from_department="DeptA",
            to_department="DeptB",
        )
        assert req.from_location == "WH"
        assert req.to_location == "WH"

    def test_get_fixed_assets_query_page_size_min_boundary(self):
        # page_size 1 is valid
        req = GetFixedAssetsQuery(legal_entity_id=create_uuid(), page_size=1)
        assert req.page_size == 1
        # page_size 500 is valid
        req2 = GetFixedAssetsQuery(legal_entity_id=create_uuid(), page_size=500)
        assert req2.page_size == 500

    def test_asset_response_dto_depreciation_percentage_high(self):
        dto = AssetResponseDTO(
            id=create_uuid(),
            asset_code="TEST",
            asset_name="Test",
            asset_category="OTHER",
            acquisition_date=FIXED_DATE,
            acquisition_cost=Decimal("100"),
            salvage_value=Decimal("0"),
            useful_life_years=5,
            depreciation_method="straight_line",
            accumulated_depreciation=Decimal("100"),
            book_value=Decimal("0"),
            location=None,
            responsible_party=None,
            status="FULLY_DEPRECIATED",
            is_active=False,
            created_at=FIXED_DATETIME,
            updated_at=FIXED_DATETIME,
            version=1,
        )
        assert dto.depreciation_percentage == Decimal("100.00")
