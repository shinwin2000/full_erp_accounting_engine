#!/usr/bin/env python3
"""
Module: legal_entity_repository_port.py
Layer: Ports (Primary)
Responsibility: Implementasi in-memory repository untuk Legal Entity (Entitas Hukum).
               Mendukung multi-entitas, konsolidasi grup, alamat, kontak, NPWP,
               pengaturan pajak, mata uang fungsional, tahun fiskal, status aktif,
               audit trail, import/export CSV, dan statistik.
Audit: Setiap perubahan pada entitas hukum (tambah, ubah, nonaktifkan, grup) tercatat.
"""

from __future__ import annotations

import asyncio
import csv
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


class LegalEntityType(Enum):
    """Jenis entitas hukum."""

    CORPORATION = "corporation"  # Perseroan Terbatas (PT)
    LIMITED = "limited"  # CV
    SOLE_PROPRIETORSHIP = "sole"  # Perorangan (UD)
    COOPERATIVE = "cooperative"  # Koperasi
    FOUNDATION = "foundation"  # Yayasan
    GOVERNMENT = "government"  # Instansi pemerintah
    REPRESENTATIVE_OFFICE = "representative"  # Kantor perwakilan


class TaxRegime(Enum):
    """Regime perpajakan."""

    GENERAL = "general"  # Umum (PKP)
    FINAL = "final"  # Final PP 23
    SME = "sme"  # UMKM tertentu
    SPECIAL = "special"  # Perlakuan khusus


class ConsolidationMethod(Enum):
    """Metode konsolidasi."""

    FULL = "full"  # Konsolidasi penuh
    EQUITY = "equity"  # Metode ekuitas
    PROPORTIONAL = "proportional"  # Proporsional
    NONE = "none"  # Tidak dikonsolidasi


@dataclass
class Address:
    """Alamat entitas hukum."""

    street: str | None
    city: str | None
    postal_code: str | None
    province: str | None
    country: str = "Indonesia"
    is_main: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "street": self.street,
            "city": self.city,
            "postal_code": self.postal_code,
            "province": self.province,
            "country": self.country,
            "is_main": self.is_main,
        }


@dataclass
class Contact:
    """Kontak entitas hukum."""

    email: str | None
    phone: str | None
    mobile: str | None
    fax: str | None
    website: str | None
    contact_person: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "email": self.email,
            "phone": self.phone,
            "mobile": self.mobile,
            "fax": self.fax,
            "website": self.website,
            "contact_person": self.contact_person,
        }


@dataclass
class TaxProfile:
    """Profil perpajakan entitas."""

    npwp: str | None  # Nomor Pokok Wajib Pajak (15-16 digit)
    tax_regime: TaxRegime = TaxRegime.GENERAL
    is_pkp: bool = True  # Pengusaha Kena Pajak
    pkp_number: str | None = None  # Nomor Pengukuhan PKP
    tax_office: str | None = None  # KPP Pratama
    tax_office_code: str | None = None
    default_tax_rate_ppn: Decimal = Decimal("11.00")  # PPN 11% (2022+)
    default_withholding_pph21: Decimal = Decimal("0")
    default_withholding_pph23: Decimal = Decimal("2")
    use_e_faktur: bool = True
    coretax_id: str | None = None
    coretax_password: str | None = None  # akan dienkripsi

    def to_dict(self, include_secrets: bool = False) -> dict[str, Any]:
        result = {
            "npwp": self.npwp,
            "tax_regime": self.tax_regime.value,
            "is_pkp": self.is_pkp,
            "pkp_number": self.pkp_number,
            "tax_office": self.tax_office,
            "tax_office_code": self.tax_office_code,
            "default_tax_rate_ppn": float(self.default_tax_rate_ppn),
            "default_withholding_pph21": float(self.default_withholding_pph21),
            "default_withholding_pph23": float(self.default_withholding_pph23),
            "use_e_faktur": self.use_e_faktur,
            "coretax_id": self.coretax_id,
        }
        if include_secrets:
            result["coretax_password"] = self.coretax_password
        return result


@dataclass
class LegalEntity:
    """
    Aggregate Root Legal Entity.
    """

    id: UUID
    entity_code: str  # Kode unik entitas (misal: PT001)
    entity_name: str
    legal_name: str  # Nama lengkap sesuai akta
    entity_type: LegalEntityType
    registration_number: str | None  # Akta pendirian / NIB
    registration_date: date | None
    established_date: date | None
    fiscal_year_start_month: int = 1  # 1 = Januari
    fiscal_year_end_month: int = 12
    functional_currency: str = "IDR"
    reporting_currency: str = "IDR"
    addresses: list[Address] = field(default_factory=list)
    contacts: list[Contact] = field(default_factory=list)
    tax_profile: TaxProfile | None = None
    parent_entity_id: UUID | None = None  # Untuk struktur grup
    consolidation_method: ConsolidationMethod = ConsolidationMethod.NONE
    consolidation_group_id: UUID | None = None
    is_active: bool = True
    notes: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: UUID = field(default_factory=lambda: UUID(int=0))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_by: UUID = field(default_factory=lambda: UUID(int=0))
    deleted_at: datetime | None = None
    version: int = 1

    def to_dict(self, include_secrets: bool = False) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "entity_code": self.entity_code,
            "entity_name": self.entity_name,
            "legal_name": self.legal_name,
            "entity_type": self.entity_type.value,
            "registration_number": self.registration_number,
            "registration_date": self.registration_date.isoformat()
            if self.registration_date
            else None,
            "established_date": self.established_date.isoformat()
            if self.established_date
            else None,
            "fiscal_year_start_month": self.fiscal_year_start_month,
            "fiscal_year_end_month": self.fiscal_year_end_month,
            "functional_currency": self.functional_currency,
            "reporting_currency": self.reporting_currency,
            "addresses": [a.to_dict() for a in self.addresses],
            "contacts": [c.to_dict() for c in self.contacts],
            "tax_profile": self.tax_profile.to_dict(include_secrets) if self.tax_profile else None,
            "parent_entity_id": str(self.parent_entity_id) if self.parent_entity_id else None,
            "consolidation_method": self.consolidation_method.value,
            "consolidation_group_id": str(self.consolidation_group_id)
            if self.consolidation_group_id
            else None,
            "is_active": self.is_active,
            "notes": self.notes,
            "created_at": self.created_at.isoformat(),
            "created_by": str(self.created_by),
            "updated_at": self.updated_at.isoformat(),
            "updated_by": str(self.updated_by),
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "version": self.version,
        }


class LegalEntityRepositoryPort:
    """
    In-memory repository untuk Legal Entity.
    """

    def __init__(self):
        self._storage: dict[UUID, LegalEntity] = {}
        self._code_index: dict[str, LegalEntity] = {}  # entity_code -> entity
        self._npwp_index: dict[str, LegalEntity] = {}  # npwp_clean -> entity
        self._group_index: dict[
            UUID, list[UUID]
        ] = {}  # consolidation_group_id -> list of entity ids
        self._parent_index: dict[UUID, list[UUID]] = {}  # parent_entity_id -> list of child ids
        self._active_index: list[UUID] = []
        self._audit_log: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()

    # ==================== HELPER ====================

    async def _log_audit(
        self, action: str, entity_id: UUID, user_id: UUID, details: dict[str, Any]
    ):
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "action": action,
            "entity_id": str(entity_id),
            "user_id": str(user_id),
            "details": details,
        }
        self._audit_log.append(entry)
        logger.info(f"LEGAL ENTITY AUDIT: {action} on {entity_id} by {user_id}")

    async def _validate_npwp(self, npwp: str) -> tuple[bool, str | None]:
        """Validasi format NPWP Indonesia (15 digit atau 16 digit dengan kode)."""
        if not npwp:
            return True, None
        # Hapus karakter non-digit
        clean = re.sub(r"[^0-9]", "", npwp)
        if len(clean) not in (15, 16):
            return False, "NPWP must be 15 or 16 digits"
        # NPWP valid: 2 digit pertama bukan 00, 3 digit berikutnya bukan 000
        if clean[:2] == "00":
            return False, "First two digits cannot be 00"
        # Validasi sederhana checksum? Tidak diperlukan untuk simulasi
        return True, None

    async def _update_indices(self, entity: LegalEntity, is_insert: bool = True):
        # Code index (entity_code harus unik global)
        if entity.entity_code in self._code_index and (
            is_insert or self._code_index[entity.entity_code].id != entity.id
        ):
            raise ValueError(f"Entity code {entity.entity_code} already exists")
        if is_insert:
            self._code_index[entity.entity_code] = entity
        else:
            self._code_index[entity.entity_code] = entity

        # NPWP index
        if entity.tax_profile and entity.tax_profile.npwp:
            clean = re.sub(r"[^0-9]", "", entity.tax_profile.npwp)
            if clean in self._npwp_index and (is_insert or self._npwp_index[clean].id != entity.id):
                raise ValueError(f"NPWP {entity.tax_profile.npwp} already exists")
            self._npwp_index[clean] = entity

        # Group index
        if entity.consolidation_group_id:
            if entity.consolidation_group_id not in self._group_index:
                self._group_index[entity.consolidation_group_id] = []
            if entity.id not in self._group_index[entity.consolidation_group_id]:
                self._group_index[entity.consolidation_group_id].append(entity.id)

        # Parent index
        if entity.parent_entity_id:
            if entity.parent_entity_id not in self._parent_index:
                self._parent_index[entity.parent_entity_id] = []
            if entity.id not in self._parent_index[entity.parent_entity_id]:
                self._parent_index[entity.parent_entity_id].append(entity.id)

        # Active index
        if entity.is_active and entity.deleted_at is None:
            if entity.id not in self._active_index:
                self._active_index.append(entity.id)

    async def _remove_from_indices(self, entity: LegalEntity):
        if entity.entity_code in self._code_index:
            del self._code_index[entity.entity_code]
        if entity.tax_profile and entity.tax_profile.npwp:
            clean = re.sub(r"[^0-9]", "", entity.tax_profile.npwp)
            if clean in self._npwp_index:
                del self._npwp_index[clean]
        if entity.consolidation_group_id and entity.id in self._group_index.get(
            entity.consolidation_group_id, []
        ):
            self._group_index[entity.consolidation_group_id].remove(entity.id)
        if entity.parent_entity_id and entity.id in self._parent_index.get(
            entity.parent_entity_id, []
        ):
            self._parent_index[entity.parent_entity_id].remove(entity.id)
        if entity.id in self._active_index:
            self._active_index.remove(entity.id)

    # ==================== CRUD ====================

    async def add(self, entity: LegalEntity) -> None:
        if entity.id in self._storage:
            raise ValueError(f"Entity {entity.id} already exists")
        if entity.entity_code in self._code_index:
            raise ValueError(f"Entity code {entity.entity_code} already exists")
        if entity.tax_profile and entity.tax_profile.npwp:
            valid, msg = await self._validate_npwp(entity.tax_profile.npwp)
            if not valid:
                raise ValueError(f"Invalid NPWP: {msg}")
        entity.created_at = datetime.now(UTC)
        entity.updated_at = entity.created_at
        entity.version = 1
        async with self._lock:
            self._storage[entity.id] = entity
            await self._update_indices(entity, is_insert=True)
        await self._log_audit(
            "ADD",
            entity.id,
            entity.created_by,
            {
                "entity_code": entity.entity_code,
                "entity_name": entity.entity_name,
                "npwp": entity.tax_profile.npwp if entity.tax_profile else None,
            },
        )

    async def get_by_id(self, entity_id: UUID) -> LegalEntity | None:
        entity = self._storage.get(entity_id)
        if entity and entity.deleted_at is not None:
            return None
        return entity

    async def get_by_tax_id(self, tax_id_number: str) -> LegalEntity | None:
        """Mencari berdasarkan NPWP (clean)."""
        clean = re.sub(r"[^0-9]", "", tax_id_number)
        return self._npwp_index.get(clean)

    async def get_by_code(self, entity_code: str) -> LegalEntity | None:
        return self._code_index.get(entity_code)

    async def update(self, entity: LegalEntity) -> None:
        if entity.id not in self._storage:
            raise ValueError(f"Entity {entity.id} not found")
        old = self._storage[entity.id]
        if old.deleted_at is not None:
            raise ValueError("Cannot update deleted entity")
        # Validasi NPWP baru
        if entity.tax_profile and entity.tax_profile.npwp:
            valid, msg = await self._validate_npwp(entity.tax_profile.npwp)
            if not valid:
                raise ValueError(f"Invalid NPWP: {msg}")
        # Hapus dari index lama
        await self._remove_from_indices(old)
        # Update field
        entity.created_at = old.created_at
        entity.created_by = old.created_by
        entity.updated_at = datetime.now(UTC)
        entity.version = old.version + 1
        # Simpan
        async with self._lock:
            self._storage[entity.id] = entity
            await self._update_indices(entity, is_insert=True)
        await self._log_audit(
            "UPDATE",
            entity.id,
            entity.updated_by,
            {
                "entity_code": entity.entity_code,
                "changes": "multiple",
            },
        )

    async def delete(self, entity_id: UUID, user_id: UUID, permanent: bool = False) -> bool:
        entity = self._storage.get(entity_id)
        if not entity:
            return False
        if permanent:
            await self._remove_from_indices(entity)
            del self._storage[entity_id]
            await self._log_audit("DELETE_PERMANENT", entity_id, user_id, {})
        else:
            entity.deleted_at = datetime.now(UTC)
            entity.is_active = False
            entity.updated_by = user_id
            entity.updated_at = entity.deleted_at
            entity.version += 1
            await self._remove_from_indices(entity)
            await self._update_indices(entity, is_insert=True)  # will mark as inactive
            await self._log_audit("DELETE_SOFT", entity_id, user_id, {})
        return True

    async def restore(self, entity_id: UUID, user_id: UUID) -> bool:
        entity = self._storage.get(entity_id)
        if not entity or entity.deleted_at is None:
            return False
        entity.deleted_at = None
        entity.is_active = True
        entity.updated_by = user_id
        entity.updated_at = datetime.now(UTC)
        entity.version += 1
        await self._update_indices(entity, is_insert=True)
        await self._log_audit("RESTORE", entity_id, user_id, {})
        return True

    # ==================== QUERY ====================

    async def find_all_active(self) -> list[LegalEntity]:
        result = []
        for eid in self._active_index:
            entity = self._storage.get(eid)
            if entity and entity.deleted_at is None and entity.is_active:
                result.append(entity)
        return result

    async def get_consolidation_group(self, group_id: UUID) -> list[LegalEntity]:
        ids = self._group_index.get(group_id, [])
        return [
            self._storage[eid]
            for eid in ids
            if eid in self._storage and self._storage[eid].deleted_at is None
        ]

    async def get_children(self, parent_entity_id: UUID) -> list[LegalEntity]:
        ids = self._parent_index.get(parent_entity_id, [])
        return [
            self._storage[eid]
            for eid in ids
            if eid in self._storage and self._storage[eid].deleted_at is None
        ]

    async def get_tree(self, root_entity_id: UUID) -> dict[str, Any]:
        """Mengembalikan struktur hirarki entitas (root dan anak-anak)."""
        root = await self.get_by_id(root_entity_id)
        if not root:
            return {}

        async def build_tree(entity_id: UUID) -> dict[str, Any]:
            entity = await self.get_by_id(entity_id)
            if not entity:
                return {}
            children = await self.get_children(entity_id)
            return {
                "id": str(entity.id),
                "code": entity.entity_code,
                "name": entity.entity_name,
                "type": entity.entity_type.value,
                "children": [await build_tree(child.id) for child in children],
            }

        return await build_tree(root_entity_id)

    async def find_by_name_contains(self, keyword: str, limit: int = 20) -> list[LegalEntity]:
        keyword_lower = keyword.lower()
        result = []
        for entity in self._storage.values():
            if entity.deleted_at is not None:
                continue
            if (
                keyword_lower in entity.entity_name.lower()
                or keyword_lower in entity.legal_name.lower()
            ):
                result.append(entity)
        return sorted(result, key=lambda x: x.entity_name)[:limit]

    async def get_all(
        self, include_inactive: bool = False, limit: int = 100, offset: int = 0
    ) -> list[LegalEntity]:
        result = list(self._storage.values())
        if not include_inactive:
            result = [e for e in result if e.deleted_at is None and e.is_active]
        result.sort(key=lambda x: x.entity_code)
        return result[offset : offset + limit]

    # ==================== TAX & UTILITY ====================

    async def get_tax_profile(self, entity_id: UUID) -> TaxProfile | None:
        entity = await self.get_by_id(entity_id)
        return entity.tax_profile if entity else None

    async def update_tax_profile(
        self, entity_id: UUID, tax_profile: TaxProfile, user_id: UUID
    ) -> bool:
        entity = await self.get_by_id(entity_id)
        if not entity:
            return False
        old_npwp = entity.tax_profile.npwp if entity.tax_profile else None
        new_npwp = tax_profile.npwp
        if new_npwp and new_npwp != old_npwp:
            valid, msg = await self._validate_npwp(new_npwp)
            if not valid:
                raise ValueError(f"Invalid NPWP: {msg}")
            clean = re.sub(r"[^0-9]", "", new_npwp)
            existing = self._npwp_index.get(clean)
            if existing and existing.id != entity.id:
                raise ValueError(f"NPWP {new_npwp} already belongs to {existing.entity_name}")
        entity.tax_profile = tax_profile
        entity.updated_by = user_id
        entity.updated_at = datetime.now(UTC)
        entity.version += 1
        await self.update(entity)
        await self._log_audit("UPDATE_TAX_PROFILE", entity_id, user_id, {"npwp": new_npwp})
        return True

    async def get_fiscal_year_range(self, entity_id: UUID, fiscal_year: int) -> tuple[date, date]:
        entity = await self.get_by_id(entity_id)
        if not entity:
            raise ValueError("Entity not found")
        start_month = entity.fiscal_year_start_month
        end_month = entity.fiscal_year_end_month
        start_date = date(fiscal_year, start_month, 1)
        if end_month == 12:
            end_date = date(fiscal_year, 12, 31)
        else:
            end_date = date(fiscal_year, end_month + 1, 1) - timedelta(days=1)
        return start_date, end_date

    async def get_previous_fiscal_year(self, entity_id: UUID, fiscal_year: int) -> int:
        entity = await self.get_by_id(entity_id)
        if not entity:
            return fiscal_year - 1
        start_month = entity.fiscal_year_start_month
        if start_month == 1:
            return fiscal_year - 1
        else:
            return fiscal_year

    # ==================== IMPORT/EXPORT ====================

    async def export_to_csv(self) -> str:
        entities = await self.get_all(include_inactive=True)
        import io

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            ["entity_code", "entity_name", "legal_name", "type", "npwp", "currency", "is_active"]
        )
        for e in entities:
            npwp = e.tax_profile.npwp if e.tax_profile else ""
            writer.writerow(
                [
                    e.entity_code,
                    e.entity_name,
                    e.legal_name,
                    e.entity_type.value,
                    npwp,
                    e.functional_currency,
                    "1" if e.is_active else "0",
                ]
            )
        return output.getvalue()

    async def import_from_csv(self, csv_content: str, user_id: UUID) -> int:
        import io

        reader = csv.DictReader(io.StringIO(csv_content))
        count = 0
        for row in reader:
            try:
                tax_profile = TaxProfile(npwp=row.get("npwp") or None)
                entity = LegalEntity(
                    id=uuid4(),
                    entity_code=row["entity_code"],
                    entity_name=row["entity_name"],
                    legal_name=row["legal_name"],
                    entity_type=LegalEntityType(row["type"]),
                    registration_number=None,
                    registration_date=None,
                    established_date=None,
                    fiscal_year_start_month=1,
                    fiscal_year_end_month=12,
                    functional_currency=row.get("currency", "IDR"),
                    reporting_currency=row.get("currency", "IDR"),
                    tax_profile=tax_profile,
                    is_active=row.get("is_active") == "1",
                    created_by=user_id,
                    updated_by=user_id,
                )
                await self.add(entity)
                count += 1
            except Exception as e:
                logger.warning(f"Import legal entity failed: {e}")
        return count

    # ==================== STATISTICS & AUDIT ====================

    async def get_statistics(self) -> dict[str, Any]:
        entities = list(self._storage.values())
        total = len(entities)
        active = sum(1 for e in entities if e.is_active and e.deleted_at is None)
        by_type = {t.value: 0 for t in LegalEntityType}
        for e in entities:
            if e.deleted_at is None:
                by_type[e.entity_type.value] = by_type.get(e.entity_type.value, 0) + 1
        return {
            "total_entities": total,
            "active_entities": active,
            "inactive_entities": total - active,
            "by_type": by_type,
            "with_tax_profile": sum(1 for e in entities if e.tax_profile and e.tax_profile.npwp),
            "in_consolidation_groups": sum(1 for e in entities if e.consolidation_group_id),
            "has_parent": sum(1 for e in entities if e.parent_entity_id),
        }

    async def get_audit_log(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        return self._audit_log[offset : offset + limit]

    async def health_check(self) -> dict[str, Any]:
        return {
            "status": "healthy",
            "total_entities": len(self._storage),
            "total_npwp_indexed": len(self._npwp_index),
            "total_groups": len(self._group_index),
            "audit_log_size": len(self._audit_log),
        }
