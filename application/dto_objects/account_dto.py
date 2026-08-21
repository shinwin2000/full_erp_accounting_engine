# account_dto.py - Hardened version with complete implementation

#!/usr/bin/env python3

"""
Module: account_dto.py
Layer: 8 - Application / DTO Objects

Responsibility: Data Transfer Objects untuk Chart of Accounts (COA).

Fitur:
- Validasi lengkap untuk semua request/response
- Serialisasi ke/dari dictionary
- Factory methods untuk pembuatan DTO
- Hierarki akun dengan tree structure
- Bulk import support
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

# === 1. ENUMS ===


class AccountTypeDTO(str, Enum):
    """Jenis akun untuk DTO."""

    ASSET = "ASSET"
    LIABILITY = "LIABILITY"
    EQUITY = "EQUITY"
    REVENUE = "REVENUE"
    EXPENSE = "EXPENSE"
    CONTRA_ASSET = "CONTRA_ASSET"
    CONTRA_LIABILITY = "CONTRA_LIABILITY"
    CONTRA_EQUITY = "CONTRA_EQUITY"

    @classmethod
    def get_normal_balance(cls, account_type: str) -> str:
        """Get normal balance for account type."""
        normal_balances = {
            "ASSET": "debit",
            "CONTRA_ASSET": "credit",
            "LIABILITY": "credit",
            "CONTRA_LIABILITY": "debit",
            "EQUITY": "credit",
            "CONTRA_EQUITY": "debit",
            "REVENUE": "credit",
            "EXPENSE": "debit",
        }
        return normal_balances.get(account_type, "debit")

    def is_asset(self) -> bool:
        return self in (self.ASSET, self.CONTRA_ASSET)

    def is_liability(self) -> bool:
        return self in (self.LIABILITY, self.CONTRA_LIABILITY)

    def is_equity(self) -> bool:
        return self in (self.EQUITY, self.CONTRA_EQUITY)

    def is_income_statement(self) -> bool:
        return self in (self.REVENUE, self.EXPENSE)

    def is_balance_sheet(self) -> bool:
        return self in (
            self.ASSET,
            self.LIABILITY,
            self.EQUITY,
            self.CONTRA_ASSET,
            self.CONTRA_LIABILITY,
            self.CONTRA_EQUITY,
        )


class AccountStatusDTO(str, Enum):
    """Status akun."""

    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    LOCKED = "LOCKED"
    CLOSED = "CLOSED"

    def is_active(self) -> bool:
        return self == self.ACTIVE

    def can_post(self) -> bool:
        return self in (self.ACTIVE, self.INACTIVE)


class AccountNormalBalance(str, Enum):
    """Normal balance for account."""

    DEBIT = "debit"
    CREDIT = "credit"

    def opposite(self) -> AccountNormalBalance:
        return (
            AccountNormalBalance.CREDIT
            if self == AccountNormalBalance.DEBIT
            else AccountNormalBalance.DEBIT
        )


# === 2. REQUEST DTOS ===


@dataclass(kw_only=True)
class CreateAccountRequest:
    """Request DTO untuk membuat akun baru."""

    legal_entity_id: UUID
    account_code: str
    name: str
    account_type: str
    parent_account_id: UUID | None = None
    description: str | None = None
    opening_balance: Decimal = Decimal("0")
    currency_code: str = "IDR"
    is_header: bool = False
    is_active: bool = True
    tax_code: str | None = None
    financial_report_section: str | None = None

    def __post_init__(self) -> None:
        """Validasi dasar DTO."""
        if not self.account_code or len(self.account_code.strip()) < 3:
            raise ValueError("Account code must be at least 3 characters")
        if not self.name or len(self.name.strip()) < 2:
            raise ValueError("Account name must be at least 2 characters")
        if self.account_type not in [t.value for t in AccountTypeDTO]:
            raise ValueError(
                f"Invalid account_type: {self.account_type}. Must be one of {[t.value for t in AccountTypeDTO]}"
            )
        if self.opening_balance < 0:
            raise ValueError(f"Opening balance cannot be negative: {self.opening_balance}")
        if self.currency_code not in ["IDR", "USD", "EUR", "SGD", "JPY", "CNY"]:
            raise ValueError(f"Invalid currency_code: {self.currency_code}")

    def get_normal_balance(self) -> str:
        """Get normal balance based on account type."""
        return AccountTypeDTO.get_normal_balance(self.account_type)

    def to_dict(self) -> dict[str, Any]:
        return {
            "legal_entity_id": str(self.legal_entity_id),
            "account_code": self.account_code,
            "name": self.name,
            "account_type": self.account_type,
            "parent_account_id": str(self.parent_account_id) if self.parent_account_id else None,
            "description": self.description,
            "opening_balance": str(self.opening_balance),
            "currency_code": self.currency_code,
            "is_header": self.is_header,
            "is_active": self.is_active,
            "tax_code": self.tax_code,
            "financial_report_section": self.financial_report_section,
            "normal_balance": self.get_normal_balance(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CreateAccountRequest:
        return cls(
            legal_entity_id=UUID(data["legal_entity_id"]),
            account_code=data["account_code"],
            name=data["name"],
            account_type=data["account_type"],
            parent_account_id=UUID(data["parent_account_id"])
            if data.get("parent_account_id")
            else None,
            description=data.get("description"),
            opening_balance=Decimal(str(data.get("opening_balance", 0))),
            currency_code=data.get("currency_code", "IDR"),
            is_header=data.get("is_header", False),
            is_active=data.get("is_active", True),
            tax_code=data.get("tax_code"),
            financial_report_section=data.get("financial_report_section"),
        )


@dataclass(kw_only=True)
class UpdateAccountRequest:
    """Request DTO untuk memperbarui akun."""

    account_id: UUID
    name: str | None = None
    description: str | None = None
    parent_account_id: UUID | None = None
    opening_balance: Decimal | None = None
    status: str | None = None
    deactivation_reason: str | None = None
    tax_code: str | None = None
    financial_report_section: str | None = None

    def __post_init__(self) -> None:
        """Validasi dasar DTO."""
        if not any(
            [
                self.name,
                self.description,
                self.parent_account_id,
                self.opening_balance,
                self.status,
                self.deactivation_reason,
                self.tax_code,
                self.financial_report_section,
            ]
        ):
            raise ValueError("At least one field to update must be provided")
        if self.name and len(self.name.strip()) < 2:
            raise ValueError("Account name must be at least 2 characters")
        if self.status and self.status not in [s.value for s in AccountStatusDTO]:
            raise ValueError(f"Invalid status: {self.status}")
        if self.opening_balance is not None and self.opening_balance < 0:
            raise ValueError(f"Opening balance cannot be negative: {self.opening_balance}")

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        if self.name is not None:
            result["name"] = self.name
        if self.description is not None:
            result["description"] = self.description
        if self.parent_account_id is not None:
            result["parent_account_id"] = (
                str(self.parent_account_id) if self.parent_account_id else None
            )
        if self.opening_balance is not None:
            result["opening_balance"] = str(self.opening_balance)
        if self.status is not None:
            result["status"] = self.status
        if self.deactivation_reason is not None:
            result["deactivation_reason"] = self.deactivation_reason
        if self.tax_code is not None:
            result["tax_code"] = self.tax_code
        if self.financial_report_section is not None:
            result["financial_report_section"] = self.financial_report_section
        result["account_id"] = str(self.account_id)
        return result


@dataclass(kw_only=True)
class GetAccountRequest:
    """Request DTO untuk mendapatkan detail akun."""

    account_id: UUID
    legal_entity_id: UUID

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_id": str(self.account_id),
            "legal_entity_id": str(self.legal_entity_id),
        }


@dataclass(kw_only=True)
class GetAccountByCodeRequest:
    """Request DTO untuk mendapatkan akun berdasarkan kode."""

    legal_entity_id: UUID
    account_code: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "legal_entity_id": str(self.legal_entity_id),
            "account_code": self.account_code,
        }


@dataclass(kw_only=True)
class GetAccountsQuery:
    """Query parameters untuk listing accounts."""

    legal_entity_id: UUID
    account_type: str | None = None
    is_active: bool | None = None
    parent_account_id: UUID | None = None
    search: str | None = None
    include_children: bool = True
    include_headers: bool = True
    page: int = 1
    page_size: int = 20

    def __post_init__(self) -> None:
        if self.page < 1:
            raise ValueError("page must be >= 1")
        if self.page_size < 1 or self.page_size > 500:
            raise ValueError("page_size must be between 1 and 500")
        if self.account_type and self.account_type not in [t.value for t in AccountTypeDTO]:
            raise ValueError(f"Invalid account_type: {self.account_type}")

    def get_offset(self) -> int:
        return (self.page - 1) * self.page_size

    def to_dict(self) -> dict[str, Any]:
        return {
            "legal_entity_id": str(self.legal_entity_id),
            "account_type": self.account_type,
            "is_active": self.is_active,
            "parent_account_id": str(self.parent_account_id) if self.parent_account_id else None,
            "search": self.search,
            "include_children": self.include_children,
            "include_headers": self.include_headers,
            "page": self.page,
            "page_size": self.page_size,
            "offset": self.get_offset(),
        }


# === 3. RESPONSE DTOS ===


@dataclass(kw_only=True)
class AccountResponse:
    """Response DTO untuk data akun."""

    id: UUID
    legal_entity_id: UUID
    account_code: str
    name: str
    account_type: str
    normal_balance: str
    parent_account_id: UUID | None
    description: str | None
    opening_balance: Decimal
    currency_code: str
    is_header: bool
    level: int
    status: str
    created_at: datetime
    created_by: UUID | None
    updated_at: datetime | None
    updated_by: UUID | None
    version: int = 1
    tax_code: str | None = None
    financial_report_section: str | None = None
    current_balance: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if self.created_at.tzinfo is None:
            object.__setattr__(self, "created_at", self.created_at.replace(tzinfo=UTC))
        if self.updated_at and self.updated_at.tzinfo is None:
            object.__setattr__(self, "updated_at", self.updated_at.replace(tzinfo=UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "legal_entity_id": str(self.legal_entity_id),
            "account_code": self.account_code,
            "name": self.name,
            "account_type": self.account_type,
            "normal_balance": self.normal_balance,
            "parent_account_id": str(self.parent_account_id) if self.parent_account_id else None,
            "description": self.description,
            "opening_balance": str(self.opening_balance),
            "current_balance": str(self.current_balance),
            "currency_code": self.currency_code,
            "is_header": self.is_header,
            "level": self.level,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "created_by": str(self.created_by) if self.created_by else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "updated_by": str(self.updated_by) if self.updated_by else None,
            "version": self.version,
            "tax_code": self.tax_code,
            "financial_report_section": self.financial_report_section,
        }

    def is_debit_balance(self) -> bool:
        """Check if normal balance is debit."""
        return self.normal_balance == "debit"

    def is_credit_balance(self) -> bool:
        """Check if normal balance is credit."""
        return self.normal_balance == "credit"


@dataclass(kw_only=True)
class AccountHierarchyNodeDTO:
    """DTO untuk node dalam hierarki akun."""

    id: UUID | None
    account_code: str
    name: str
    account_type: str
    normal_balance: str
    level: int
    children: list[AccountHierarchyNodeDTO]
    is_header: bool = False
    status: str = "ACTIVE"
    opening_balance: Decimal = Decimal("0")
    current_balance: Decimal = Decimal("0")
    description: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id) if self.id else None,
            "account_code": self.account_code,
            "name": self.name,
            "account_type": self.account_type,
            "normal_balance": self.normal_balance,
            "level": self.level,
            "children": [c.to_dict() for c in self.children],
            "is_header": self.is_header,
            "status": self.status,
            "opening_balance": str(self.opening_balance),
            "current_balance": str(self.current_balance),
            "description": self.description,
        }

    def total_balance(self) -> Decimal:
        """Calculate total balance including children."""
        total = self.current_balance
        for child in self.children:
            total += child.total_balance()
        return total

    def flatten(self) -> list[AccountHierarchyNodeDTO]:
        """Flatten hierarchy into list."""
        result = [self]
        for child in self.children:
            result.extend(child.flatten())
        return result

    def find_child_by_code(self, account_code: str) -> AccountHierarchyNodeDTO | None:
        """Find child by account code."""
        if self.account_code == account_code:
            return self
        for child in self.children:
            found = child.find_child_by_code(account_code)
            if found:
                return found
        return None

    def find_child_by_id(self, account_id: UUID) -> AccountHierarchyNodeDTO | None:
        """Find child by account ID."""
        if self.id == account_id:
            return self
        for child in self.children:
            found = child.find_child_by_id(account_id)
            if found:
                return found
        return None


@dataclass(kw_only=True)
class AccountBalanceResponse:
    """Response DTO untuk saldo akun."""

    account_id: UUID
    account_code: str
    account_name: str
    opening_balance: Decimal
    period_debit: Decimal
    period_credit: Decimal
    ending_balance: Decimal
    normal_balance: str
    period_start: datetime
    period_end: datetime
    currency_code: str = "IDR"

    def __post_init__(self) -> None:
        if self.period_start.tzinfo is None:
            object.__setattr__(self, "period_start", self.period_start.replace(tzinfo=UTC))
        if self.period_end.tzinfo is None:
            object.__setattr__(self, "period_end", self.period_end.replace(tzinfo=UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_id": str(self.account_id),
            "account_code": self.account_code,
            "account_name": self.account_name,
            "opening_balance": str(self.opening_balance),
            "period_debit": str(self.period_debit),
            "period_credit": str(self.period_credit),
            "ending_balance": str(self.ending_balance),
            "normal_balance": self.normal_balance,
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "currency_code": self.currency_code,
        }

    def is_debit_balance(self) -> bool:
        """Check if ending balance is debit."""
        if self.normal_balance == "debit":
            return self.ending_balance > 0
        return self.ending_balance < 0

    def get_absolute_balance(self) -> Decimal:
        """Get absolute value of ending balance."""
        return abs(self.ending_balance)


@dataclass(kw_only=True)
class BulkImportResultDTO:
    """DTO untuk hasil bulk import akun."""

    total_rows: int
    success_count: int
    failure_count: int
    failures: list[dict[str, Any]]
    created_accounts: list[AccountResponse]
    warnings: list[str] = field(default_factory=list)
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.started_at.tzinfo is None:
            object.__setattr__(self, "started_at", self.started_at.replace(tzinfo=UTC))
        if self.completed_at and self.completed_at.tzinfo is None:
            object.__setattr__(self, "completed_at", self.completed_at.replace(tzinfo=UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_rows": self.total_rows,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "failures": self.failures,
            "created_accounts": [acc.to_dict() for acc in self.created_accounts],
            "warnings": self.warnings,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "success_rate": self.get_success_rate(),
        }

    def get_success_rate(self) -> float:
        """Calculate success rate percentage."""
        if self.total_rows == 0:
            return 100.0
        return (self.success_count / self.total_rows) * 100

    def complete(self) -> None:
        """Mark import as completed."""
        self.completed_at = datetime.now(UTC)

    def add_failure(self, row: int, error: str) -> None:
        """Add a failure entry."""
        self.failures.append({"row": row, "error": error})
        self.failure_count += 1

    def add_success(self, account: AccountResponse) -> None:
        """Add a successful import."""
        self.created_accounts.append(account)
        self.success_count += 1


@dataclass(kw_only=True)
class AccountValidationResult:
    """Result of account validation."""

    is_valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "errors": self.errors,
            "warnings": self.warnings,
        }

    def add_error(self, error: str) -> None:
        self.errors.append(error)
        self.is_valid = False

    def add_warning(self, warning: str) -> None:
        self.warnings.append(warning)


# === 4. FACTORY ===


class AccountDTOFactory:
    """Factory untuk membuat Account DTOs."""

    @staticmethod
    def create_account_response(
        account_id: UUID,
        legal_entity_id: UUID,
        account_code: str,
        name: str,
        account_type: str,
        normal_balance: str,
        parent_account_id: UUID | None,
        level: int,
        created_by: UUID | None = None,
        description: str | None = None,
        opening_balance: Decimal = Decimal("0"),
        currency_code: str = "IDR",
        is_header: bool = False,
        status: str = "ACTIVE",
        tax_code: str | None = None,
        financial_report_section: str | None = None,
    ) -> AccountResponse:
        """Create account response DTO."""
        return AccountResponse(
            id=account_id,
            legal_entity_id=legal_entity_id,
            account_code=account_code,
            name=name,
            account_type=account_type,
            normal_balance=normal_balance,
            parent_account_id=parent_account_id,
            description=description,
            opening_balance=opening_balance,
            currency_code=currency_code,
            is_header=is_header,
            level=level,
            status=status,
            created_at=datetime.now(UTC),
            created_by=created_by,
            updated_at=None,
            updated_by=None,
            tax_code=tax_code,
            financial_report_section=financial_report_section,
        )

    @staticmethod
    def create_hierarchy_node(
        account_code: str,
        name: str,
        account_type: str,
        normal_balance: str,
        level: int,
        is_header: bool = False,
        account_id: UUID | None = None,
        status: str = "ACTIVE",
        opening_balance: Decimal = Decimal("0"),
        current_balance: Decimal = Decimal("0"),
        description: str | None = None,
        children: list[AccountHierarchyNodeDTO] | None = None,
    ) -> AccountHierarchyNodeDTO:
        """Create hierarchy node DTO."""
        return AccountHierarchyNodeDTO(
            id=account_id,
            account_code=account_code,
            name=name,
            account_type=account_type,
            normal_balance=normal_balance,
            level=level,
            children=children or [],
            is_header=is_header,
            status=status,
            opening_balance=opening_balance,
            current_balance=current_balance,
            description=description,
        )

    @staticmethod
    def create_balance_response(
        account_id: UUID,
        account_code: str,
        account_name: str,
        opening_balance: Decimal,
        period_debit: Decimal,
        period_credit: Decimal,
        ending_balance: Decimal,
        normal_balance: str,
        period_start: datetime,
        period_end: datetime,
        currency_code: str = "IDR",
    ) -> AccountBalanceResponse:
        """Create account balance response DTO."""
        return AccountBalanceResponse(
            account_id=account_id,
            account_code=account_code,
            account_name=account_name,
            opening_balance=opening_balance,
            period_debit=period_debit,
            period_credit=period_credit,
            ending_balance=ending_balance,
            normal_balance=normal_balance,
            period_start=period_start,
            period_end=period_end,
            currency_code=currency_code,
        )


# === 5. ALIASES FOR COMPATIBILITY ===

AccountCreateRequest = CreateAccountRequest
AccountUpdateRequest = UpdateAccountRequest
AccountGetRequest = GetAccountRequest
AccountListQuery = GetAccountsQuery
AccountHierarchyDTO = AccountHierarchyNodeDTO
AccountBalanceDTO = AccountBalanceResponse


# === 6. EXPORTS ===

__all__ = [
    "AccountBalanceDTO",
    "AccountBalanceResponse",
    # Aliases
    "AccountCreateRequest",
    # Factory
    "AccountDTOFactory",
    "AccountGetRequest",
    "AccountHierarchyDTO",
    "AccountHierarchyNodeDTO",
    "AccountListQuery",
    "AccountNormalBalance",
    # Response DTOs
    "AccountResponse",
    "AccountStatusDTO",
    # Enums
    "AccountTypeDTO",
    "AccountUpdateRequest",
    "AccountValidationResult",
    "BulkImportResultDTO",
    # Request DTOs
    "CreateAccountRequest",
    "GetAccountByCodeRequest",
    "GetAccountRequest",
    "GetAccountsQuery",
    "UpdateAccountRequest",
]
