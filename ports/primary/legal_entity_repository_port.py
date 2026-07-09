#!/usr/bin/env python3
"""
Module: legal_entity_repository_port.py
Layer: Ports (Primary)
Responsibility: Port interface untuk repository Legal Entity.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID


class LegalEntityType(Enum):
    CORPORATION = "corporation"
    LIMITED = "limited"
    SOLE_PROPRIETORSHIP = "sole"
    COOPERATIVE = "cooperative"
    FOUNDATION = "foundation"
    GOVERNMENT = "government"
    REPRESENTATIVE_OFFICE = "representative"


class TaxRegime(Enum):
    GENERAL = "general"
    FINAL = "final"
    SME = "sme"
    SPECIAL = "special"


class ConsolidationMethod(Enum):
    FULL = "full"
    EQUITY = "equity"
    PROPORTIONAL = "proportional"
    NONE = "none"


@dataclass
class Address:
    street: str | None
    city: str | None
    postal_code: str | None
    province: str | None
    country: str = "Indonesia"
    is_main: bool = True


@dataclass
class Contact:
    email: str | None
    phone: str | None
    mobile: str | None
    fax: str | None
    website: str | None
    contact_person: str | None


@dataclass
class TaxProfile:
    npwp: str | None
    tax_regime: TaxRegime = TaxRegime.GENERAL
    is_pkp: bool = True
    pkp_number: str | None = None
    tax_office: str | None = None
    tax_office_code: str | None = None
    default_tax_rate_ppn: Decimal = Decimal("11.00")
    default_withholding_pph21: Decimal = Decimal("0")
    default_withholding_pph23: Decimal = Decimal("2")
    use_e_faktur: bool = True
    coretax_id: str | None = None
    coretax_password: str | None = None  # akan dienkripsi


@dataclass
class LegalEntity:
    id: UUID
    entity_code: str
    entity_name: str
    legal_name: str
    entity_type: LegalEntityType
    registration_number: str | None
    registration_date: date | None
    established_date: date | None
    fiscal_year_start_month: int = 1
    fiscal_year_end_month: int = 12
    functional_currency: str = "IDR"
    reporting_currency: str = "IDR"
    addresses: list[Address] = field(default_factory=list)
    contacts: list[Contact] = field(default_factory=list)
    tax_profile: TaxProfile | None = None
    parent_entity_id: UUID | None = None
    consolidation_method: ConsolidationMethod = ConsolidationMethod.NONE
    consolidation_group_id: UUID | None = None
    is_active: bool = True
    notes: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now())
    created_by: UUID = field(default_factory=lambda: UUID(int=0))
    updated_at: datetime = field(default_factory=lambda: datetime.now())
    updated_by: UUID = field(default_factory=lambda: UUID(int=0))
    deleted_at: datetime | None = None
    version: int = 1


class LegalEntityRepositoryPort(ABC):
    """
    Port interface untuk repository Legal Entity.
    """

    # ---------- CRUD ----------
    @abstractmethod
    async def add(self, entity: LegalEntity) -> None:
        pass

    @abstractmethod
    async def update(self, entity: LegalEntity) -> None:
        pass

    @abstractmethod
    async def delete(self, entity_id: UUID, user_id: UUID, permanent: bool = False) -> bool:
        pass

    @abstractmethod
    async def restore(self, entity_id: UUID, user_id: UUID) -> bool:
        pass

    # ---------- Query ----------
    @abstractmethod
    async def get_by_id(self, entity_id: UUID) -> LegalEntity | None:
        pass

    @abstractmethod
    async def get_by_npwp(self, npwp: str) -> LegalEntity | None:
        pass

    @abstractmethod
    async def get_by_tax_id(self, tax_id: str) -> LegalEntity | None:
        pass

    @abstractmethod
    async def get_by_code(self, entity_code: str) -> LegalEntity | None:
        pass

    @abstractmethod
    async def find_all_active(self) -> list[LegalEntity]:
        pass

    @abstractmethod
    async def get_all(self, include_inactive: bool = False, limit: int = 100, offset: int = 0) -> list[LegalEntity]:
        pass

    @abstractmethod
    async def get_children(self, parent_entity_id: UUID) -> list[LegalEntity]:
        pass

    @abstractmethod
    async def get_tree(self, root_entity_id: UUID) -> dict[str, Any]:
        pass

    @abstractmethod
    async def exists_by_npwp(self, npwp: str) -> bool:
        pass

    @abstractmethod
    async def find_by_name_contains(self, name_fragment: str, limit: int = 50) -> list[LegalEntity]:
        pass

    # ---------- Tax ----------
    @abstractmethod
    async def get_tax_profile(self, entity_id: UUID) -> TaxProfile | None:
        pass

    @abstractmethod
    async def update_tax_profile(self, entity_id: UUID, tax_profile: TaxProfile, user_id: UUID) -> bool:
        pass

    @abstractmethod
    async def get_fiscal_year_range(self, entity_id: UUID, fiscal_year: int) -> tuple[date, date]:
        pass

    @abstractmethod
    async def get_previous_fiscal_year(self, entity_id: UUID, fiscal_year: int) -> int:
        pass

    # ---------- Branch ----------
    @abstractmethod
    async def add_branch(self, branch: dict[str, Any]) -> UUID:
        pass

    @abstractmethod
    async def get_branches(self, parent_entity_id: UUID) -> list[dict[str, Any]]:
        pass

    # ---------- Consolidation ----------
    @abstractmethod
    async def create_consolidation_group(self, group_name: str, description: str | None = None, created_by: UUID | None = None) -> UUID:
        pass

    @abstractmethod
    async def add_to_consolidation_group(self, group_id: UUID, entity_id: UUID, ownership_percentage: Decimal) -> None:
        pass

    @abstractmethod
    async def get_consolidation_groups(self, is_active: bool = True) -> list[dict[str, Any]]:
        pass

    @abstractmethod
    async def get_consolidation_group(self, group_id: UUID) -> list[LegalEntity]:
        pass

    # ---------- Export / Import ----------
    @abstractmethod
    async def export_to_csv(self) -> str:
        pass

    @abstractmethod
    async def import_from_csv(self, csv_content: str, created_by: UUID) -> int:
        pass

    # ---------- Statistics & Audit ----------
    @abstractmethod
    async def get_statistics(self) -> dict[str, Any]:
        pass

    @abstractmethod
    async def get_audit_log(self, entity_id: UUID | None = None, limit: int = 100) -> list[dict[str, Any]]:
        pass

    @abstractmethod
    async def health_check(self) -> dict[str, Any]:
        pass


__all__ = [
    "Address",
    "ConsolidationMethod",
    "Contact",
    "LegalEntity",
    "LegalEntityRepositoryPort",
    "LegalEntityType",
    "TaxProfile",
    "TaxRegime",
]