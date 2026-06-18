#!/usr/bin/env python3
"""
Module: company_entity.py
Layer: 6 - Domain / Legal Entity
Responsibility: Entitas perusahaan: nama, alamat, NPWP, kode entitas.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID

from domain.shared_value_objects.npwp_vo import NPWP


# --- Definisi lokal untuk memutus circular import dengan aggregate_root.py ---
class LegalEntityType(Enum):
    CORPORATION = "corporation"
    LIMITED = "limited"
    SOLE_PROPRIETORSHIP = "sole"
    PARTNERSHIP = "partnership"
    COOPERATIVE = "cooperative"
    NON_PROFIT = "non_profit"
    GOVERNMENT = "government"


class LegalEntityStatus(Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    DISSOLVED = "dissolved"


logger = logging.getLogger(__name__)


@dataclass
class CompanyEntity:
    company_id: UUID
    legal_entity_id: UUID
    trade_name: str
    legal_name: str
    entity_type: LegalEntityType
    npwp: NPWP
    address: str
    city: str
    province: str
    postal_code: str
    country: str
    phone: str | None = None
    email: str | None = None
    website: str | None = None
    established_date: datetime | None = None
    business_license_number: str | None = None
    business_license_date: datetime | None = None
    pkp_status: bool = False
    pkp_registration_date: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    version: int = 1

    def __post_init__(self) -> None:
        if not self.trade_name or len(self.trade_name.strip()) < 2:
            raise ValueError("Trade name must be at least 2 characters")
        if not self.legal_name or len(self.legal_name.strip()) < 2:
            raise ValueError("Legal name must be at least 2 characters")
        if not self.address or len(self.address.strip()) < 5:
            raise ValueError("Address must be at least 5 characters")
        if not self.city or len(self.city.strip()) < 2:
            raise ValueError("City must be at least 2 characters")
        if not self.province or len(self.province.strip()) < 2:
            raise ValueError("Province must be at least 2 characters")
        if self.version < 1:
            raise ValueError("Version must be >= 1")

    def update_address(
        self,
        address: str,
        city: str,
        province: str,
        postal_code: str,
        country: str,
        updated_by: str,
    ) -> CompanyEntity:
        return CompanyEntity(
            company_id=self.company_id,
            legal_entity_id=self.legal_entity_id,
            trade_name=self.trade_name,
            legal_name=self.legal_name,
            entity_type=self.entity_type,
            npwp=self.npwp,
            address=address,
            city=city,
            province=province,
            postal_code=postal_code,
            country=country,
            phone=self.phone,
            email=self.email,
            website=self.website,
            established_date=self.established_date,
            business_license_number=self.business_license_number,
            business_license_date=self.business_license_date,
            pkp_status=self.pkp_status,
            pkp_registration_date=self.pkp_registration_date,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            version=self.version + 1,
        )

    def update_contact(
        self,
        phone: str | None,
        email: str | None,
        website: str | None,
        updated_by: str,
    ) -> CompanyEntity:
        return CompanyEntity(
            company_id=self.company_id,
            legal_entity_id=self.legal_entity_id,
            trade_name=self.trade_name,
            legal_name=self.legal_name,
            entity_type=self.entity_type,
            npwp=self.npwp,
            address=self.address,
            city=self.city,
            province=self.province,
            postal_code=self.postal_code,
            country=self.country,
            phone=phone,
            email=email,
            website=website,
            established_date=self.established_date,
            business_license_number=self.business_license_number,
            business_license_date=self.business_license_date,
            pkp_status=self.pkp_status,
            pkp_registration_date=self.pkp_registration_date,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            version=self.version + 1,
        )

    def register_pkp(self, registration_date: datetime, registered_by: str) -> CompanyEntity:
        return CompanyEntity(
            company_id=self.company_id,
            legal_entity_id=self.legal_entity_id,
            trade_name=self.trade_name,
            legal_name=self.legal_name,
            entity_type=self.entity_type,
            npwp=self.npwp,
            address=self.address,
            city=self.city,
            province=self.province,
            postal_code=self.postal_code,
            country=self.country,
            phone=self.phone,
            email=self.email,
            website=self.website,
            established_date=self.established_date,
            business_license_number=self.business_license_number,
            business_license_date=self.business_license_date,
            pkp_status=True,
            pkp_registration_date=registration_date,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            version=self.version + 1,
        )

    def is_pkp(self) -> bool:
        return self.pkp_status

    def to_dict(self) -> dict[str, Any]:
        return {
            "company_id": str(self.company_id),
            "legal_entity_id": str(self.legal_entity_id),
            "trade_name": self.trade_name,
            "legal_name": self.legal_name,
            "entity_type": self.entity_type.value,
            "npwp": str(self.npwp),
            "address": self.address,
            "city": self.city,
            "province": self.province,
            "postal_code": self.postal_code,
            "country": self.country,
            "phone": self.phone,
            "email": self.email,
            "website": self.website,
            "established_date": self.established_date.isoformat()
            if self.established_date
            else None,
            "business_license_number": self.business_license_number,
            "pkp_status": self.pkp_status,
            "pkp_registration_date": self.pkp_registration_date.isoformat()
            if self.pkp_registration_date
            else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "version": self.version,
        }


class CompanyEntityRepository:
    async def get_by_id(self, company_id: UUID) -> CompanyEntity | None:
        raise NotImplementedError

    async def get_by_legal_entity(self, legal_entity_id: UUID) -> CompanyEntity | None:
        raise NotImplementedError

    async def get_by_npwp(self, npwp: str) -> CompanyEntity | None:
        raise NotImplementedError

    async def save(self, company: CompanyEntity) -> None:
        raise NotImplementedError

    async def delete(self, company_id: UUID) -> None:
        raise NotImplementedError


Company = CompanyEntity

__all__ = [
    "Company",
    "CompanyEntity",
    "CompanyEntityRepository",
    "LegalEntityStatus",
    "LegalEntityType",
]
