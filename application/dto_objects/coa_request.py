# coa_request.py - Hardened version with complete implementation

#!/usr/bin/env python3
"""
Module: coa_request.py
Layer: Application / DTO Objects
Responsibility: Data Transfer Objects for Chart of Accounts (COA) requests.

Fitur:
- Create, update, get, list accounts
- Account type validation
- Hierarchical account structure support
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID


@dataclass(kw_only=True)
class CreateAccountRequest:
    """Request DTO for creating a new chart of account."""

    account_code: str
    account_name: str
    account_type: str  # asset, liability, equity, revenue, expense
    parent_account_id: UUID | None = None
    is_active: bool = True
    description: str | None = None
    currency: str = "IDR"
    normal_balance: str = "debit"
    financial_report_section: str | None = None
    tax_code: str | None = None
    legal_entity_id: UUID | None = None
    opening_balance: str = "0"

    def __post_init__(self) -> None:
        if not self.account_code or len(self.account_code.strip()) < 3:
            raise ValueError("Account code must be at least 3 characters")
        if not self.account_name or len(self.account_name.strip()) < 2:
            raise ValueError("Account name must be at least 2 characters")
        valid_types = [
            "asset",
            "liability",
            "equity",
            "revenue",
            "expense",
            "contra_asset",
            "contra_liability",
            "contra_equity",
        ]
        if self.account_type.lower() not in valid_types:
            raise ValueError(
                f"Invalid account_type: {self.account_type}. Must be one of {valid_types}"
            )
        if self.normal_balance.lower() not in ["debit", "credit"]:
            raise ValueError("normal_balance must be 'debit' or 'credit'")

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_code": self.account_code,
            "account_name": self.account_name,
            "account_type": self.account_type,
            "parent_account_id": str(self.parent_account_id) if self.parent_account_id else None,
            "is_active": self.is_active,
            "description": self.description,
            "currency": self.currency,
            "normal_balance": self.normal_balance,
            "financial_report_section": self.financial_report_section,
            "tax_code": self.tax_code,
            "legal_entity_id": str(self.legal_entity_id) if self.legal_entity_id else None,
            "opening_balance": self.opening_balance,
        }


@dataclass(kw_only=True)
class UpdateAccountRequest:
    """Request DTO for updating an existing account."""

    account_id: UUID
    account_name: str | None = None
    description: str | None = None
    is_active: bool | None = None
    parent_account_id: UUID | None = None
    tax_code: str | None = None
    financial_report_section: str | None = None

    def __post_init__(self) -> None:
        if not any(
            [
                self.account_name,
                self.description,
                self.is_active is not None,
                self.parent_account_id,
                self.tax_code,
                self.financial_report_section,
            ]
        ):
            raise ValueError("At least one field to update must be provided")
        if self.account_name and len(self.account_name.strip()) < 2:
            raise ValueError("Account name must be at least 2 characters")

    def to_dict(self) -> dict[str, Any]:
        result = {"account_id": str(self.account_id)}
        if self.account_name is not None:
            result["account_name"] = self.account_name
        if self.description is not None:
            result["description"] = self.description
        if self.is_active is not None:
            result["is_active"] = self.is_active
        if self.parent_account_id is not None:
            result["parent_account_id"] = str(self.parent_account_id)
        if self.tax_code is not None:
            result["tax_code"] = self.tax_code
        if self.financial_report_section is not None:
            result["financial_report_section"] = self.financial_report_section
        return result


@dataclass(kw_only=True)
class GetAccountsQuery:
    """Query parameters for listing accounts."""

    legal_entity_id: UUID
    account_type: str | None = None
    is_active: bool | None = None
    parent_account_id: UUID | None = None
    search: str | None = None
    include_children: bool = True
    page: int = 1
    page_size: int = 20

    def __post_init__(self) -> None:
        if self.page < 1:
            raise ValueError("page must be >= 1")
        if self.page_size < 1 or self.page_size > 500:
            raise ValueError("page_size must be between 1 and 500")

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
            "page": self.page,
            "page_size": self.page_size,
            "offset": self.get_offset(),
        }


@dataclass(kw_only=True)
class GetAccountRequest:
    """Request DTO for getting a single account."""

    account_id: UUID
    legal_entity_id: UUID

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_id": str(self.account_id),
            "legal_entity_id": str(self.legal_entity_id),
        }


@dataclass(kw_only=True)
class DeleteAccountRequest:
    """Request DTO for deleting (deactivating) an account."""

    account_id: UUID
    legal_entity_id: UUID
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_id": str(self.account_id),
            "legal_entity_id": str(self.legal_entity_id),
            "reason": self.reason,
        }


# Aliases for router compatibility
AccountCreateRequest = CreateAccountRequest
AccountUpdateRequest = UpdateAccountRequest
AccountQueryParams = GetAccountsQuery
AccountGetRequest = GetAccountRequest


__all__ = [
    "AccountCreateRequest",
    "AccountGetRequest",
    "AccountQueryParams",
    "AccountUpdateRequest",
    "CreateAccountRequest",
    "DeleteAccountRequest",
    "GetAccountRequest",
    "GetAccountsQuery",
    "UpdateAccountRequest",
]
