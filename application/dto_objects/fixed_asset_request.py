# fixed_asset_request.py - Hardened version with complete implementation

#!/usr/bin/env python3
"""
Module: fixed_asset_request.py
Layer: Application / DTO Objects
Responsibility: Data Transfer Objects for Fixed Asset Management requests.

Fitur:
- Asset creation, update, disposal
- Depreciation run
- Impairment testing
- Revaluation
- Asset categorization
- Component tracking
- Maintenance scheduling
- Asset transfer between locations
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from enum import Enum
from typing import Any
from uuid import UUID

# === 1. ENUMS ===


class AssetStatus(str, Enum):
    """Status aset tetap - mirrors fastapi_fixed_asset_router.py's own
    AssetStatus enum exactly, since that's the enum whose .value is what
    actually arrives here in update/status-change requests."""

    DRAFT = "draft"
    ACTIVE = "active"
    IN_USE = "in_use"
    UNDER_MAINTENANCE = "under_maintenance"
    IDLE = "idle"
    FULLY_DEPRECIATED = "fully_depreciated"
    DISPOSED = "disposed"
    SOLD = "sold"
    SCRAPPED = "scrapped"
    IMPAIRED = "impaired"
    LOCKED = "locked"


class DepreciationMethod(str, Enum):
    """Metode depresiasi."""

    STRAIGHT_LINE = "straight_line"
    DECLINING_BALANCE = "declining_balance"
    DOUBLE_DECLINING = "double_declining"
    SUM_OF_YEARS = "sum_of_years"
    UNITS_OF_PRODUCTION = "units_of_production"


class AssetCategory(str, Enum):
    """Kategori aset tetap."""

    BUILDING = "BUILDING"
    MACHINERY = "MACHINERY"
    VEHICLE = "VEHICLE"
    FURNITURE = "FURNITURE"
    COMPUTER = "COMPUTER"
    SOFTWARE = "SOFTWARE"
    LAND = "LAND"
    OTHER = "OTHER"


class DisposalReason(str, Enum):
    """Alasan disposal aset."""

    SOLD = "SOLD"
    SCRAPPED = "SCRAPPED"
    DONATED = "DONATED"
    LOST = "LOST"
    STOLEN = "STOLEN"
    TRADED_IN = "TRADED_IN"


# === 2. REQUEST DTOS ===


@dataclass(kw_only=True)
class AssetCreateRequest:
    """Request DTO for creating a new fixed asset.

    FIX: field names/types here now mirror exactly what
    fastapi_fixed_asset_router.py's create_asset() endpoint constructs from
    AssetCreateSchema (asset_category as a plain str - the enum's .value -
    not asset_category_id; residual_value not salvage_value; invoice_id not
    invoice_number; responsible_party as free text, not a UUID; plus the
    depreciation_rate/is_component/parent_asset_id/notes/
    revaluation_frequency/use_fiscal_depreciation/created_by fields the
    router always sends). The old field set didn't match at all, so every
    POST /fixed-assets/assets failed immediately with
    "AssetCreateRequest.__init__() got an unexpected keyword argument
    'asset_category'" before the request ever reached the service layer.
    """

    asset_code: str
    asset_name: str
    asset_category: str
    acquisition_date: date
    acquisition_cost: Decimal
    residual_value: Decimal = Decimal(0)
    useful_life_years: int = 5
    depreciation_method: str = "straight_line"
    depreciation_rate: Decimal | None = None
    location: str | None = None
    responsible_party: str | None = None
    supplier_id: UUID | None = None
    purchase_order_id: UUID | None = None
    invoice_id: UUID | None = None
    serial_number: str | None = None
    is_active: bool = True
    is_component: bool = False
    parent_asset_id: UUID | None = None
    notes: str | None = None
    revaluation_frequency: str = "never"
    use_fiscal_depreciation: bool = False
    created_by: UUID | None = None
    legal_entity_id: UUID | None = None
    description: str | None = None
    warranty_expiry_date: date | None = None
    insurance_policy_number: str | None = None
    insurance_expiry_date: date | None = None
    model_number: str | None = None

    def __post_init__(self) -> None:
        if not self.asset_code or len(self.asset_code.strip()) < 3:
            raise ValueError("Asset code must be at least 3 characters")
        if not self.asset_name:
            raise ValueError("Asset name is required")
        if self.acquisition_cost <= 0:
            raise ValueError(f"Acquisition cost must be positive: {self.acquisition_cost}")
        if self.residual_value < 0:
            raise ValueError(f"Residual value cannot be negative: {self.residual_value}")
        if self.residual_value > self.acquisition_cost:
            raise ValueError("Residual value cannot exceed acquisition cost")
        if self.useful_life_years < 1:
            raise ValueError(f"Useful life must be at least 1 year: {self.useful_life_years}")
        valid_methods = [m.value for m in DepreciationMethod]
        if self.depreciation_method.lower() not in valid_methods:
            raise ValueError(f"Invalid depreciation_method: {self.depreciation_method}")

    @property
    def depreciable_amount(self) -> Decimal:
        """Calculate depreciable amount."""
        return (self.acquisition_cost - self.residual_value).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_EVEN
        )

    @property
    def annual_depreciation_straight_line(self) -> Decimal:
        """Calculate annual depreciation for straight-line method."""
        if self.useful_life_years > 0:
            return (self.depreciable_amount / Decimal(self.useful_life_years)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_EVEN
            )
        return Decimal(0)

    @property
    def monthly_depreciation_straight_line(self) -> Decimal:
        """Calculate monthly depreciation for straight-line method."""
        return (self.annual_depreciation_straight_line / Decimal(12)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_EVEN
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_code": self.asset_code,
            "asset_name": self.asset_name,
            "asset_category": self.asset_category,
            "acquisition_date": self.acquisition_date.isoformat(),
            "acquisition_cost": str(self.acquisition_cost),
            "residual_value": str(self.residual_value),
            "useful_life_years": self.useful_life_years,
            "depreciation_method": self.depreciation_method,
            "depreciation_rate": str(self.depreciation_rate) if self.depreciation_rate is not None else None,
            "location": self.location,
            "responsible_party": self.responsible_party,
            "description": self.description,
            "supplier_id": str(self.supplier_id) if self.supplier_id else None,
            "purchase_order_id": str(self.purchase_order_id) if self.purchase_order_id else None,
            "invoice_id": str(self.invoice_id) if self.invoice_id else None,
            "is_active": self.is_active,
            "is_component": self.is_component,
            "parent_asset_id": str(self.parent_asset_id) if self.parent_asset_id else None,
            "notes": self.notes,
            "revaluation_frequency": self.revaluation_frequency,
            "use_fiscal_depreciation": self.use_fiscal_depreciation,
            "created_by": str(self.created_by) if self.created_by else None,
            "legal_entity_id": str(self.legal_entity_id) if self.legal_entity_id else None,
            "warranty_expiry_date": self.warranty_expiry_date.isoformat()
            if self.warranty_expiry_date
            else None,
            "insurance_policy_number": self.insurance_policy_number,
            "insurance_expiry_date": self.insurance_expiry_date.isoformat()
            if self.insurance_expiry_date
            else None,
            "serial_number": self.serial_number,
            "model_number": self.model_number,
            "depreciable_amount": str(self.depreciable_amount),
            "annual_depreciation": str(self.annual_depreciation_straight_line),
            "monthly_depreciation": str(self.monthly_depreciation_straight_line),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AssetCreateRequest:
        return cls(
            asset_code=data["asset_code"],
            asset_name=data["asset_name"],
            asset_category=data["asset_category"],
            acquisition_date=date.fromisoformat(data["acquisition_date"]),
            acquisition_cost=Decimal(str(data["acquisition_cost"])),
            residual_value=Decimal(str(data.get("residual_value", 0))),
            useful_life_years=data.get("useful_life_years", 5),
            depreciation_method=data.get("depreciation_method", "straight_line"),
            depreciation_rate=Decimal(str(data["depreciation_rate"]))
            if data.get("depreciation_rate")
            else None,
            location=data.get("location"),
            responsible_party=data.get("responsible_party"),
            description=data.get("description"),
            supplier_id=UUID(data["supplier_id"]) if data.get("supplier_id") else None,
            purchase_order_id=UUID(data["purchase_order_id"])
            if data.get("purchase_order_id")
            else None,
            invoice_id=UUID(data["invoice_id"]) if data.get("invoice_id") else None,
            is_active=data.get("is_active", True),
            is_component=data.get("is_component", False),
            parent_asset_id=UUID(data["parent_asset_id"]) if data.get("parent_asset_id") else None,
            notes=data.get("notes"),
            revaluation_frequency=data.get("revaluation_frequency", "never"),
            use_fiscal_depreciation=data.get("use_fiscal_depreciation", False),
            created_by=UUID(data["created_by"]) if data.get("created_by") else None,
            legal_entity_id=UUID(data["legal_entity_id"]) if data.get("legal_entity_id") else None,
            warranty_expiry_date=date.fromisoformat(data["warranty_expiry_date"])
            if data.get("warranty_expiry_date")
            else None,
            insurance_policy_number=data.get("insurance_policy_number"),
            insurance_expiry_date=date.fromisoformat(data["insurance_expiry_date"])
            if data.get("insurance_expiry_date")
            else None,
            serial_number=data.get("serial_number"),
            model_number=data.get("model_number"),
        )


@dataclass(kw_only=True)
class UpdateFixedAssetRequest:
    """Request DTO for updating a fixed asset.

    FIX: field names now mirror what fastapi_fixed_asset_router.py's
    update_asset() endpoint actually constructs from AssetUpdateSchema (id
    not asset_id, residual_value not salvage_value, responsible_party as
    free text not a UUID, plus notes/updated_by which the router always
    sends and the old field set didn't accept at all). This was the direct
    cause of "UpdateFixedAssetRequest.__init__() got an unexpected keyword
    argument 'id'".
    """

    id: UUID
    asset_name: str | None = None
    asset_category: str | None = None
    acquisition_cost: Decimal | None = None
    location: str | None = None
    responsible_party: str | None = None
    description: str | None = None
    residual_value: Decimal | None = None
    useful_life_years: int | None = None
    depreciation_method: str | None = None
    is_active: bool | None = None
    notes: str | None = None
    legal_entity_id: UUID | None = None
    status: str | None = None
    updated_by: UUID | None = None
    warranty_expiry_date: date | None = None
    insurance_policy_number: str | None = None
    insurance_expiry_date: date | None = None

    def __post_init__(self) -> None:
        if not any(
            [
                self.asset_name,
                self.asset_category,
                self.acquisition_cost,
                self.location,
                self.responsible_party,
                self.description,
                self.residual_value,
                self.useful_life_years,
                self.depreciation_method,
                self.is_active is not None,
                self.notes,
                self.status,
                self.warranty_expiry_date,
                self.insurance_policy_number,
                self.insurance_expiry_date,
            ]
        ):
            raise ValueError("At least one field to update must be provided")
        if self.asset_name and len(self.asset_name.strip()) < 2:
            raise ValueError("Asset name must be at least 2 characters")
        if self.acquisition_cost is not None and self.acquisition_cost <= 0:
            raise ValueError(f"Acquisition cost must be positive: {self.acquisition_cost}")
        if self.residual_value is not None and self.residual_value < 0:
            raise ValueError(f"Residual value cannot be negative: {self.residual_value}")
        if self.useful_life_years is not None and self.useful_life_years < 1:
            raise ValueError(f"Useful life must be at least 1 year: {self.useful_life_years}")
        if self.status and self.status not in [s.value for s in AssetStatus]:
            raise ValueError(f"Invalid status: {self.status}")

    def to_dict(self) -> dict[str, Any]:
        result = {"id": str(self.id)}
        if self.asset_name is not None:
            result["asset_name"] = self.asset_name
        if self.asset_category is not None:
            result["asset_category"] = self.asset_category
        if self.acquisition_cost is not None:
            result["acquisition_cost"] = str(self.acquisition_cost)
        if self.location is not None:
            result["location"] = self.location
        if self.responsible_party is not None:
            result["responsible_party"] = self.responsible_party
        if self.description is not None:
            result["description"] = self.description
        if self.residual_value is not None:
            result["residual_value"] = str(self.residual_value)
        if self.useful_life_years is not None:
            result["useful_life_years"] = self.useful_life_years
        if self.depreciation_method is not None:
            result["depreciation_method"] = self.depreciation_method
        if self.is_active is not None:
            result["is_active"] = self.is_active
        if self.notes is not None:
            result["notes"] = self.notes
        if self.legal_entity_id is not None:
            result["legal_entity_id"] = str(self.legal_entity_id)
        if self.status is not None:
            result["status"] = self.status
        if self.updated_by is not None:
            result["updated_by"] = str(self.updated_by)
        if self.warranty_expiry_date is not None:
            result["warranty_expiry_date"] = self.warranty_expiry_date.isoformat()
        if self.insurance_policy_number is not None:
            result["insurance_policy_number"] = self.insurance_policy_number
        if self.insurance_expiry_date is not None:
            result["insurance_expiry_date"] = self.insurance_expiry_date.isoformat()
        return result


@dataclass(kw_only=True)
class FixedAssetDisposalRequest:
    """Request DTO for disposing a fixed asset."""

    asset_id: UUID
    disposal_date: date
    disposal_reason: str
    proceeds_from_sale: Decimal = Decimal(0)
    disposal_cost: Decimal = Decimal(0)
    notes: str | None = None
    legal_entity_id: UUID | None = None
    buyer_name: str | None = None
    invoice_number: str | None = None

    def __post_init__(self) -> None:
        if not self.disposal_reason or len(self.disposal_reason.strip()) < 5:
            raise ValueError("Disposal reason must be at least 5 characters")
        if self.proceeds_from_sale < 0:
            raise ValueError(f"Proceeds from sale cannot be negative: {self.proceeds_from_sale}")
        if self.disposal_cost < 0:
            raise ValueError(f"Disposal cost cannot be negative: {self.disposal_cost}")

    @property
    def net_proceeds(self) -> Decimal:
        """Calculate net proceeds from disposal."""
        return (self.proceeds_from_sale - self.disposal_cost).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_EVEN
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_id": str(self.asset_id),
            "disposal_date": self.disposal_date.isoformat(),
            "disposal_reason": self.disposal_reason,
            "proceeds_from_sale": str(self.proceeds_from_sale),
            "disposal_cost": str(self.disposal_cost),
            "net_proceeds": str(self.net_proceeds),
            "notes": self.notes,
            "legal_entity_id": str(self.legal_entity_id) if self.legal_entity_id else None,
            "buyer_name": self.buyer_name,
            "invoice_number": self.invoice_number,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FixedAssetDisposalRequest:
        return cls(
            asset_id=UUID(data["asset_id"]),
            disposal_date=date.fromisoformat(data["disposal_date"]),
            disposal_reason=data["disposal_reason"],
            proceeds_from_sale=Decimal(str(data.get("proceeds_from_sale", 0))),
            disposal_cost=Decimal(str(data.get("disposal_cost", 0))),
            notes=data.get("notes"),
            legal_entity_id=UUID(data["legal_entity_id"]) if data.get("legal_entity_id") else None,
            buyer_name=data.get("buyer_name"),
            invoice_number=data.get("invoice_number"),
        )


@dataclass(kw_only=True)
class FixedAssetDepreciationRequest:
    """Request DTO for manual depreciation run."""

    as_of_date: date
    asset_ids: list[UUID] | None = None
    period: str = "monthly"  # monthly, quarterly, yearly
    legal_entity_id: UUID | None = None
    create_journal: bool = True
    journal_description: str | None = None

    def __post_init__(self) -> None:
        valid_periods = ["monthly", "quarterly", "yearly"]
        if self.period.lower() not in valid_periods:
            raise ValueError(f"Invalid period: {self.period}. Must be one of {valid_periods}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of_date": self.as_of_date.isoformat(),
            "asset_ids": [str(aid) for aid in self.asset_ids] if self.asset_ids else None,
            "period": self.period,
            "legal_entity_id": str(self.legal_entity_id) if self.legal_entity_id else None,
            "create_journal": self.create_journal,
            "journal_description": self.journal_description,
        }


@dataclass(kw_only=True)
class ImpairmentTestRequest:
    """Request DTO for asset impairment testing."""

    asset_id: UUID
    test_date: date
    recoverable_amount: Decimal
    notes: str | None = None
    legal_entity_id: UUID | None = None
    approved_by: UUID | None = None

    def __post_init__(self) -> None:
        if self.recoverable_amount < 0:
            raise ValueError(f"Recoverable amount cannot be negative: {self.recoverable_amount}")

    @property
    def impairment_loss(self) -> Decimal:
        """Placeholder - actual impairment loss depends on carrying amount."""
        return Decimal(0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_id": str(self.asset_id),
            "test_date": self.test_date.isoformat(),
            "recoverable_amount": str(self.recoverable_amount),
            "notes": self.notes,
            "legal_entity_id": str(self.legal_entity_id) if self.legal_entity_id else None,
            "approved_by": str(self.approved_by) if self.approved_by else None,
            "impairment_loss": str(self.impairment_loss),
        }


@dataclass(kw_only=True)
class RevaluationRequest:
    """Request DTO for fixed asset revaluation."""

    asset_id: UUID
    new_acquisition_cost: Decimal
    revaluation_date: date
    notes: str | None = None
    legal_entity_id: UUID | None = None
    approved_by: UUID | None = None
    appraisal_firm: str | None = None
    appraisal_number: str | None = None

    def __post_init__(self) -> None:
        if self.new_acquisition_cost <= 0:
            raise ValueError(f"New acquisition cost must be positive: {self.new_acquisition_cost}")

    @property
    def revaluation_increase(self) -> Decimal:
        """Placeholder - actual increase depends on current book value."""
        return Decimal(0)

    @property
    def revaluation_decrease(self) -> Decimal:
        """Placeholder - actual decrease depends on current book value."""
        return Decimal(0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_id": str(self.asset_id),
            "new_acquisition_cost": str(self.new_acquisition_cost),
            "revaluation_date": self.revaluation_date.isoformat(),
            "notes": self.notes,
            "legal_entity_id": str(self.legal_entity_id) if self.legal_entity_id else None,
            "approved_by": str(self.approved_by) if self.approved_by else None,
            "appraisal_firm": self.appraisal_firm,
            "appraisal_number": self.appraisal_number,
            "revaluation_increase": str(self.revaluation_increase),
            "revaluation_decrease": str(self.revaluation_decrease),
        }


@dataclass(kw_only=True)
class AssetTransferRequest:
    """Request DTO for transferring asset between locations or departments."""

    asset_id: UUID
    transfer_date: date
    from_location: str
    to_location: str
    from_department: str | None = None
    to_department: str | None = None
    responsible_party: UUID | None = None
    notes: str | None = None
    legal_entity_id: UUID | None = None
    approved_by: UUID | None = None

    def __post_init__(self) -> None:
        if not self.from_location or not self.to_location:
            raise ValueError("From location and to location are required")
        if self.from_location == self.to_location:
            if self.from_department == self.to_department:
                raise ValueError("Source and destination cannot be the same")

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_id": str(self.asset_id),
            "transfer_date": self.transfer_date.isoformat(),
            "from_location": self.from_location,
            "to_location": self.to_location,
            "from_department": self.from_department,
            "to_department": self.to_department,
            "responsible_party": str(self.responsible_party) if self.responsible_party else None,
            "notes": self.notes,
            "legal_entity_id": str(self.legal_entity_id) if self.legal_entity_id else None,
            "approved_by": str(self.approved_by) if self.approved_by else None,
        }


@dataclass(kw_only=True)
class AssetMaintenanceRequest:
    """Request DTO for recording asset maintenance."""

    asset_id: UUID
    maintenance_date: date
    maintenance_type: str  # PREVENTIVE, CORRECTIVE, EMERGENCY
    cost: Decimal
    description: str
    vendor_id: UUID | None = None
    invoice_number: str | None = None
    next_maintenance_date: date | None = None
    notes: str | None = None
    legal_entity_id: UUID | None = None

    def __post_init__(self) -> None:
        valid_types = ["PREVENTIVE", "CORRECTIVE", "EMERGENCY"]
        if self.maintenance_type.upper() not in valid_types:
            raise ValueError(f"Invalid maintenance_type: {self.maintenance_type}")
        if self.cost < 0:
            raise ValueError(f"Cost cannot be negative: {self.cost}")
        if not self.description:
            raise ValueError("Description is required")

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_id": str(self.asset_id),
            "maintenance_date": self.maintenance_date.isoformat(),
            "maintenance_type": self.maintenance_type,
            "cost": str(self.cost),
            "description": self.description,
            "vendor_id": str(self.vendor_id) if self.vendor_id else None,
            "invoice_number": self.invoice_number,
            "next_maintenance_date": self.next_maintenance_date.isoformat()
            if self.next_maintenance_date
            else None,
            "notes": self.notes,
            "legal_entity_id": str(self.legal_entity_id) if self.legal_entity_id else None,
        }


@dataclass(kw_only=True)
class GetFixedAssetsQuery:
    """Query DTO for listing fixed assets."""

    legal_entity_id: UUID
    asset_category_id: UUID | None = None
    location: str | None = None
    is_active: bool | None = True
    is_fully_depreciated: bool | None = None
    acquisition_date_from: date | None = None
    acquisition_date_to: date | None = None
    status: str | None = None
    responsible_party: UUID | None = None
    search: str | None = None
    page: int = 1
    page_size: int = 20

    def __post_init__(self) -> None:
        if self.page < 1:
            raise ValueError("page must be >= 1")
        if self.page_size < 1 or self.page_size > 500:
            raise ValueError("page_size must be between 1 and 500")
        if self.status and self.status not in [s.value for s in AssetStatus]:
            raise ValueError(f"Invalid status: {self.status}")

    def get_offset(self) -> int:
        return (self.page - 1) * self.page_size

    def to_dict(self) -> dict[str, Any]:
        return {
            "legal_entity_id": str(self.legal_entity_id),
            "asset_category_id": str(self.asset_category_id) if self.asset_category_id else None,
            "location": self.location,
            "is_active": self.is_active,
            "is_fully_depreciated": self.is_fully_depreciated,
            "acquisition_date_from": self.acquisition_date_from.isoformat()
            if self.acquisition_date_from
            else None,
            "acquisition_date_to": self.acquisition_date_to.isoformat()
            if self.acquisition_date_to
            else None,
            "status": self.status,
            "responsible_party": str(self.responsible_party) if self.responsible_party else None,
            "search": self.search,
            "page": self.page,
            "page_size": self.page_size,
            "offset": self.get_offset(),
        }


@dataclass(kw_only=True)
class GetAssetDetailRequest:
    """Request DTO for getting asset details."""

    asset_id: UUID
    legal_entity_id: UUID

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_id": str(self.asset_id),
            "legal_entity_id": str(self.legal_entity_id),
        }


@dataclass(kw_only=True)
class GetAssetDepreciationScheduleRequest:
    """Request DTO for getting asset depreciation schedule."""

    asset_id: UUID
    legal_entity_id: UUID
    from_date: date | None = None
    to_date: date | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_id": str(self.asset_id),
            "legal_entity_id": str(self.legal_entity_id),
            "from_date": self.from_date.isoformat() if self.from_date else None,
            "to_date": self.to_date.isoformat() if self.to_date else None,
        }


# === 3. RESPONSE DTOS ===


@dataclass(kw_only=True)
class AssetResponseDTO:
    """Response DTO for fixed asset."""

    id: UUID
    asset_code: str
    asset_name: str
    asset_category: str
    acquisition_date: date
    acquisition_cost: Decimal
    salvage_value: Decimal
    useful_life_years: int
    depreciation_method: str
    accumulated_depreciation: Decimal
    book_value: Decimal
    location: str | None
    responsible_party: str | None
    status: str
    is_active: bool
    created_at: datetime
    updated_at: datetime | None
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "asset_code": self.asset_code,
            "asset_name": self.asset_name,
            "asset_category": self.asset_category,
            "acquisition_date": self.acquisition_date.isoformat(),
            "acquisition_cost": str(self.acquisition_cost),
            "salvage_value": str(self.salvage_value),
            "useful_life_years": self.useful_life_years,
            "depreciation_method": self.depreciation_method,
            "accumulated_depreciation": str(self.accumulated_depreciation),
            "book_value": str(self.book_value),
            "location": self.location,
            "responsible_party": self.responsible_party,
            "status": self.status,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "version": self.version,
        }

    @property
    def depreciation_percentage(self) -> Decimal:
        """Calculate depreciation percentage."""
        if self.acquisition_cost > 0:
            return (self.accumulated_depreciation / self.acquisition_cost * 100).quantize(
                Decimal("0.01")
            )
        return Decimal(0)


# === 4. FACTORY ===


class FixedAssetRequestFactory:
    """Factory for creating Fixed Asset Request DTOs."""

    @staticmethod
    def create_asset(
        asset_code: str,
        asset_name: str,
        asset_category: str,
        acquisition_date: date,
        acquisition_cost: Decimal,
        legal_entity_id: UUID,
        residual_value: Decimal = Decimal(0),
        useful_life_years: int = 5,
        depreciation_method: str = "straight_line",
    ) -> AssetCreateRequest:
        return AssetCreateRequest(
            asset_code=asset_code,
            asset_name=asset_name,
            asset_category=asset_category,
            acquisition_date=acquisition_date,
            acquisition_cost=acquisition_cost,
            residual_value=residual_value,
            useful_life_years=useful_life_years,
            depreciation_method=depreciation_method,
            legal_entity_id=legal_entity_id,
        )

    @staticmethod
    def create_disposal(
        asset_id: UUID,
        disposal_date: date,
        disposal_reason: str,
        proceeds_from_sale: Decimal = Decimal(0),
        disposal_cost: Decimal = Decimal(0),
    ) -> FixedAssetDisposalRequest:
        return FixedAssetDisposalRequest(
            asset_id=asset_id,
            disposal_date=disposal_date,
            disposal_reason=disposal_reason,
            proceeds_from_sale=proceeds_from_sale,
            disposal_cost=disposal_cost,
        )

    @staticmethod
    def create_depreciation_request(
        as_of_date: date,
        legal_entity_id: UUID,
        period: str = "monthly",
    ) -> FixedAssetDepreciationRequest:
        return FixedAssetDepreciationRequest(
            as_of_date=as_of_date,
            legal_entity_id=legal_entity_id,
            period=period,
        )

    @staticmethod
    def create_impairment_test(
        asset_id: UUID,
        test_date: date,
        recoverable_amount: Decimal,
    ) -> ImpairmentTestRequest:
        return ImpairmentTestRequest(
            asset_id=asset_id,
            test_date=test_date,
            recoverable_amount=recoverable_amount,
        )

    @staticmethod
    def create_revaluation(
        asset_id: UUID,
        new_acquisition_cost: Decimal,
        revaluation_date: date,
    ) -> RevaluationRequest:
        return RevaluationRequest(
            asset_id=asset_id,
            new_acquisition_cost=new_acquisition_cost,
            revaluation_date=revaluation_date,
        )

    @staticmethod
    def create_transfer(
        asset_id: UUID,
        transfer_date: date,
        from_location: str,
        to_location: str,
    ) -> AssetTransferRequest:
        return AssetTransferRequest(
            asset_id=asset_id,
            transfer_date=transfer_date,
            from_location=from_location,
            to_location=to_location,
        )


# === 5. ALIASES FOR ROUTER COMPATIBILITY ===

CreateFixedAssetRequest = AssetCreateRequest
AssetUpdateRequest = UpdateFixedAssetRequest
DepreciationRunRequest = FixedAssetDepreciationRequest
DisposalRequest = FixedAssetDisposalRequest
AssetTransferRequestDTO = AssetTransferRequest
AssetMaintenanceRequestDTO = AssetMaintenanceRequest


# === 6. EXPORTS ===

__all__ = [
    # Enums
    "AssetStatus",
    "DepreciationMethod",
    "AssetCategory",
    "DisposalReason",
    # Request DTOs
    "AssetCreateRequest",
    "UpdateFixedAssetRequest",
    "FixedAssetDisposalRequest",
    "FixedAssetDepreciationRequest",
    "ImpairmentTestRequest",
    "RevaluationRequest",
    "AssetTransferRequest",
    "AssetMaintenanceRequest",
    "GetFixedAssetsQuery",
    "GetAssetDetailRequest",
    "GetAssetDepreciationScheduleRequest",
    # Response DTOs
    "AssetResponseDTO",
    # Factory
    "FixedAssetRequestFactory",
    # Aliases
    "CreateFixedAssetRequest",
    "AssetUpdateRequest",
    "DepreciationRunRequest",
    "DisposalRequest",
    "AssetTransferRequestDTO",
    "AssetMaintenanceRequestDTO",
]
