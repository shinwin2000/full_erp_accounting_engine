# service_supplier.py - Database-backed (refactor sinkronisasi Supplier/Vendor)
# v8.0.0 - Tambah method addresses, contacts, tags, credit history, balance history

#!/usr/bin/env python3

"""
Module: service_supplier.py

Layer: 8 - Application / Service Layer

Responsibility:
    Service untuk mengelola Supplier/Vendor. Mendelegasikan seluruh
    persistensi ke SupplierRepositoryPort (database), menjaga aturan bisnis,
    dan mempublikasikan domain event untuk setiap perubahan penting.

PERBAIKAN (2026-10-13):
- Tambah method: list_addresses, add_address, update_address, delete_address
- Tambah method: list_contacts, add_contact, update_contact, delete_contact
- Tambah method: list_tags, add_tag, remove_tag
- Tambah method: update_credit_limit, get_credit_history
- Tambah method: get_balance_history
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from ports.primary.event_publisher_port import EventPriority, EventPublisherPort
from ports.primary.supplier_repository_port import SupplierRepositoryPort

logger = logging.getLogger(__name__)


def audit(func):
    """Dummy decorator to mark methods as audited for accounting_posting_checker."""
    return func


# ============================================================================
# Enums
# ============================================================================


class SupplierStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    BLOCKED = "blocked"
    SUSPENDED = "suspended"
    BLACKLISTED = "blacklisted"
    DRAFT = "draft"


class WithholdingCategory(str, Enum):
    NONE = "none"
    PPH23 = "pph23"
    PPH26 = "pph26"
    BOTH = "both"


# ============================================================================
# DTO Supplier
# ============================================================================


@dataclass(kw_only=True)
class Supplier:
    id: UUID = field(default_factory=uuid4)
    legal_entity_id: UUID
    supplier_code: str
    name: str
    company_name: str | None = None
    supplier_type: str = "company"
    npwp: str | None = None
    tax_name: str | None = None
    address: str | None = None
    city: str | None = None
    province: str | None = None
    postal_code: str | None = None
    country: str = "ID"
    phone: str | None = None
    mobile: str | None = None
    email: str | None = None
    website: str | None = None
    contact_person: str | None = None
    payment_terms_days: int = 30
    credit_limit: Decimal = Decimal("0")
    opening_balance: Decimal = Decimal("0")
    opening_balance_date: date | None = None
    bank_name: str | None = None
    bank_account_number: str | None = None
    bank_account_name: str | None = None
    withholding_category: str = "none"
    remarks: str | None = None
    is_active: bool = True
    status: str = SupplierStatus.ACTIVE.value
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: UUID | None = None
    version: int = 1


# ============================================================================
# Exceptions
# ============================================================================


class SupplierServiceError(Exception):
    pass


class SupplierNotFoundError(SupplierServiceError):
    pass


class SupplierHasTransactionsError(SupplierServiceError):
    """Supplier sudah punya PO/GRN/Invoice/Payment, tidak boleh dihapus."""


# ============================================================================
# Main Service
# ============================================================================


class SupplierService:
    _stats: dict[str, int] = {"suppliers_created": 0, "suppliers_updated": 0}

    def __init__(
        self,
        repository: SupplierRepositoryPort,
        event_publisher: EventPublisherPort | None = None,
    ):
        if repository is None:
            raise ValueError(
                "SupplierService membutuhkan SupplierRepositoryPort. "
                "Lihat bootstrap/dependency_container/service_registry.py "
                "untuk cara registrasi yang benar (factory + repository)."
            )
        self._repository = repository
        self._event_publisher = event_publisher
        self._audit_trail: list[dict[str, Any]] = []

        logger.info("SupplierService initialized (database-backed)")

    # ==================== AUTHORITY CHECK ====================

    def _check_authority(self, user_id: UUID | None, permission: str) -> None:
        if user_id is None:
            logger.debug(f"System action for permission '{permission}' (no user_id)")
            return
        logger.debug(
            f"Authority check: user {user_id} permission '{permission}' passed "
            "(placeholder)"
        )

    # ==================== AUDIT ====================

    def _record_audit(
        self, action: str, details: dict[str, Any] | None = None
    ) -> None:
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "service": "SupplierService",
            "action": action,
            "details": details or {},
        }
        self._audit_trail.append(entry)
        logger.info(f"AUDIT: {action} - {details}")

    # ==================== EVENT PUBLISHING ====================

    async def _publish_event(
        self,
        event_type: str,
        aggregate_id: UUID,
        payload: dict[str, Any],
        correlation_id: str | None = None,
    ) -> None:
        if not self._event_publisher:
            return
        try:
            await self._event_publisher.publish(
                event=payload,
                event_type=event_type,
                aggregate_id=aggregate_id,
                aggregate_type="Supplier",
                metadata={"correlation_id": correlation_id}
                if correlation_id
                else None,
                priority=EventPriority.NORMAL,
            )
        except Exception as e:
            logger.warning(f"Failed to publish {event_type}: {e}")

    # ==================== VALIDATION ====================

    @staticmethod
    def _validate_payload(
        *,
        supplier_code: str,
        name: str,
        payment_terms_days: int,
        credit_limit: Decimal,
        opening_balance: Decimal,
        email: str | None,
    ) -> None:
        if not supplier_code or not supplier_code.strip():
            raise SupplierServiceError("Kode supplier wajib diisi.")
        if not name or not name.strip():
            raise SupplierServiceError("Nama supplier wajib diisi.")
        if payment_terms_days < 0 or payment_terms_days > 365:
            raise SupplierServiceError("Termin pembayaran harus antara 0-365 hari.")
        if credit_limit < 0:
            raise SupplierServiceError("Limit kredit tidak boleh negatif.")
        if opening_balance < 0:
            raise SupplierServiceError("Saldo awal tidak boleh negatif.")
        if email:
            if "@" not in email or "." not in email.split("@")[-1]:
                raise SupplierServiceError(f"Format email tidak valid: {email}")

    # ========================================================================
    # CRUD UTAMA
    # ========================================================================

    @audit
    async def create_supplier(
        self,
        legal_entity_id: UUID,
        supplier_code: str,
        name: str,
        company_name: str | None = None,
        supplier_type: str = "company",
        npwp: str | None = None,
        tax_name: str | None = None,
        address: str | None = None,
        city: str | None = None,
        province: str | None = None,
        postal_code: str | None = None,
        country: str = "ID",
        phone: str | None = None,
        mobile: str | None = None,
        email: str | None = None,
        website: str | None = None,
        contact_person: str | None = None,
        payment_terms_days: int = 30,
        credit_limit: Decimal = Decimal("0"),
        opening_balance: Decimal = Decimal("0"),
        opening_balance_date: date | None = None,
        bank_name: str | None = None,
        bank_account_number: str | None = None,
        bank_account_name: str | None = None,
        withholding_category: str = "none",
        remarks: str | None = None,
        created_by: UUID | None = None,
        correlation_id: str | None = None,
    ) -> Supplier:
        self._check_authority(created_by, "create_supplier")
        self._validate_payload(
            supplier_code=supplier_code,
            name=name,
            payment_terms_days=payment_terms_days,
            credit_limit=credit_limit,
            opening_balance=opening_balance,
            email=email,
        )

        existing = await self._repository.get_by_code(
            legal_entity_id, supplier_code.strip()
        )
        if existing:
            raise SupplierServiceError(
                f"Supplier code {supplier_code} already exists"
            )

        if npwp:
            existing_npwp = await self._repository.get_by_tax_id(npwp)
            if existing_npwp:
                raise SupplierServiceError(
                    f"NPWP {npwp} sudah dipakai oleh supplier lain"
                )

        supplier = Supplier(
            legal_entity_id=legal_entity_id,
            supplier_code=supplier_code.strip(),
            name=name.strip(),
            company_name=company_name,
            supplier_type=supplier_type,
            npwp=npwp,
            tax_name=tax_name,
            address=address,
            city=city,
            province=province,
            postal_code=postal_code,
            country=country,
            phone=phone,
            mobile=mobile,
            email=email,
            website=website,
            contact_person=contact_person,
            payment_terms_days=payment_terms_days,
            credit_limit=credit_limit,
            opening_balance=opening_balance,
            opening_balance_date=opening_balance_date,
            bank_name=bank_name,
            bank_account_number=bank_account_number,
            bank_account_name=bank_account_name,
            withholding_category=withholding_category,
            remarks=remarks,
            created_by=created_by,
            version=1,
        )

        try:
            supplier = await self._repository.add(supplier)
        except ValueError as e:
            raise SupplierServiceError(str(e)) from e

        self._stats["suppliers_created"] += 1

        if self._event_publisher:
            await self._publish_event(
                event_type="SupplierCreated",
                aggregate_id=supplier.id,
                payload={
                    "supplier_id": str(supplier.id),
                    "supplier_code": supplier.supplier_code,
                    "supplier_name": supplier.name,
                    "npwp": supplier.npwp,
                    "legal_entity_id": str(supplier.legal_entity_id),
                    "created_by": str(created_by) if created_by else "system",
                },
                correlation_id=correlation_id,
            )

        self._record_audit(
            "create_supplier",
            {
                "supplier_id": str(supplier.id),
                "supplier_code": supplier_code,
                "created_by": str(created_by) if created_by else None,
            },
        )

        logger.info(f"Supplier created: {supplier.supplier_code} - {supplier.name}")
        return supplier

    async def get_supplier(
        self, supplier_id: UUID, legal_entity_id: UUID
    ) -> Supplier | None:
        return await self._repository.get_by_id(supplier_id, legal_entity_id)

    async def list_suppliers(
        self,
        legal_entity_id: UUID,
        search: str | None = None,
        city: str | None = None,
        is_active: bool | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[Supplier], int]:
        return await self._repository.list_by_entity(
            legal_entity_id,
            search=search,
            city=city,
            status=status,
            is_active=is_active,
            limit=limit,
            offset=offset,
        )

    @audit
    async def update_supplier(
        self,
        supplier_id: UUID,
        legal_entity_id: UUID,
        name: str | None = None,
        company_name: str | None = None,
        supplier_type: str | None = None,
        npwp: str | None = None,
        tax_name: str | None = None,
        address: str | None = None,
        city: str | None = None,
        province: str | None = None,
        postal_code: str | None = None,
        country: str | None = None,
        phone: str | None = None,
        mobile: str | None = None,
        email: str | None = None,
        website: str | None = None,
        contact_person: str | None = None,
        payment_terms_days: int | None = None,
        credit_limit: Decimal | None = None,
        opening_balance: Decimal | None = None,
        opening_balance_date: date | None = None,
        bank_name: str | None = None,
        bank_account_number: str | None = None,
        bank_account_name: str | None = None,
        withholding_category: str | None = None,
        remarks: str | None = None,
        is_active: bool | None = None,
        status: str | None = None,
        updated_by: UUID | None = None,
        correlation_id: str | None = None,
    ) -> Supplier:
        self._check_authority(updated_by, "update_supplier")

        supplier = await self._repository.get_by_id(supplier_id, legal_entity_id)
        if not supplier:
            raise SupplierNotFoundError(f"Supplier {supplier_id} not found")

        changes: dict[str, Any] = {}

        def _set(attr: str, new_value: Any) -> None:
            if new_value is not None and new_value != getattr(supplier, attr):
                changes[attr] = {"old": getattr(supplier, attr), "new": new_value}
                setattr(supplier, attr, new_value)

        _set("name", name)
        _set("company_name", company_name)
        _set("supplier_type", supplier_type)
        _set("npwp", npwp)
        _set("tax_name", tax_name)
        _set("address", address)
        _set("city", city)
        _set("province", province)
        _set("postal_code", postal_code)
        _set("country", country)
        _set("phone", phone)
        _set("mobile", mobile)
        _set("email", email)
        _set("website", website)
        _set("contact_person", contact_person)
        _set("bank_name", bank_name)
        _set("bank_account_number", bank_account_number)
        _set("bank_account_name", bank_account_name)
        _set("remarks", remarks)
        _set("opening_balance_date", opening_balance_date)
        _set("is_active", is_active)
        _set("status", status)

        if (
            payment_terms_days is not None
            and payment_terms_days != supplier.payment_terms_days
        ):
            old_terms = supplier.payment_terms_days
            _set("payment_terms_days", payment_terms_days)
            if self._event_publisher:
                await self._publish_event(
                    event_type="SupplierPaymentTermsChanged",
                    aggregate_id=supplier.id,
                    payload={
                        "supplier_id": str(supplier.id),
                        "supplier_code": supplier.supplier_code,
                        "old_terms": old_terms,
                        "new_terms": payment_terms_days,
                        "updated_by": str(updated_by) if updated_by else "system",
                    },
                    correlation_id=correlation_id,
                )

        if credit_limit is not None:
            if credit_limit < 0:
                raise SupplierServiceError("Limit kredit tidak boleh negatif.")
            _set("credit_limit", credit_limit)

        if opening_balance is not None:
            if opening_balance < 0:
                raise SupplierServiceError("Saldo awal tidak boleh negatif.")
            _set("opening_balance", opening_balance)

        if (
            withholding_category is not None
            and withholding_category != supplier.withholding_category
        ):
            old_category = supplier.withholding_category
            _set("withholding_category", withholding_category)
            if self._event_publisher:
                await self._publish_event(
                    event_type="SupplierWithholdingCategoryChanged",
                    aggregate_id=supplier.id,
                    payload={
                        "supplier_id": str(supplier.id),
                        "supplier_code": supplier.supplier_code,
                        "old_category": old_category,
                        "new_category": withholding_category,
                        "updated_by": str(updated_by) if updated_by else "system",
                    },
                    correlation_id=correlation_id,
                )

        if not changes:
            return supplier

        try:
            supplier = await self._repository.update(supplier)
        except ValueError as e:
            raise SupplierServiceError(str(e)) from e

        self._stats["suppliers_updated"] += 1

        self._record_audit(
            "update_supplier",
            {
                "supplier_id": str(supplier_id),
                "changes": changes,
                "updated_by": str(updated_by) if updated_by else None,
            },
        )

        return supplier

    @audit
    async def update_withholding_category(
        self,
        supplier_id: UUID,
        legal_entity_id: UUID,
        withholding_category: str,
        updated_by: UUID,
        correlation_id: str | None = None,
    ) -> Supplier:
        return await self.update_supplier(
            supplier_id=supplier_id,
            legal_entity_id=legal_entity_id,
            withholding_category=withholding_category,
            updated_by=updated_by,
            correlation_id=correlation_id,
        )

    @audit
    async def delete_supplier(
        self,
        supplier_id: UUID,
        legal_entity_id: UUID,
        deleted_by: UUID,
    ) -> None:
        self._check_authority(deleted_by, "delete_supplier")
        supplier = await self._repository.get_by_id(supplier_id, legal_entity_id)
        if not supplier:
            raise SupplierNotFoundError(f"Supplier {supplier_id} not found")

        deleted = await self._repository.soft_delete(
            supplier_id, legal_entity_id, deleted_by
        )
        if not deleted:
            raise SupplierHasTransactionsError(
                "Supplier tidak dapat dihapus karena sudah memiliki transaksi "
                "(Purchase Order/Goods Receipt/Invoice/Payment). "
                "Nonaktifkan supplier ini sebagai gantinya."
            )

        self._record_audit(
            "delete_supplier",
            {"supplier_id": str(supplier_id), "deleted_by": str(deleted_by)},
        )

    async def get_outstanding_balance(self, supplier_id: UUID) -> Decimal:
        return await self._repository.get_outstanding_balance(supplier_id)

    async def get_statistics(self, legal_entity_id: UUID) -> dict[str, Any]:
        return await self._repository.get_statistics(legal_entity_id)

    async def get_next_code(
        self, legal_entity_id: UUID, prefix: str = "SUP"
    ) -> str:
        return await self._repository.get_next_code(legal_entity_id, prefix)

    async def export_csv(self, legal_entity_id: UUID) -> str:
        repo = self._repository
        if hasattr(repo, "export_to_csv"):
            return await repo.export_to_csv(legal_entity_id)
        import csv
        import io

        rows = await repo.export_rows(legal_entity_id)
        output = io.StringIO()
        if not rows:
            return ""
        writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        for row in rows:
            writer.writerow({k: ("" if v is None else v) for k, v in row.items()})
        return output.getvalue()

    # ========================================================================
    # ATTACHMENTS
    # ========================================================================

    async def list_attachments(
        self, supplier_id: UUID, legal_entity_id: UUID
    ) -> list[dict]:
        supplier = await self._repository.get_by_id(supplier_id, legal_entity_id)
        if not supplier:
            raise SupplierNotFoundError(f"Supplier {supplier_id} not found")
        return await self._repository.list_attachments(supplier_id)

    async def add_attachment(
        self,
        supplier_id: UUID,
        legal_entity_id: UUID,
        document_type: str = "other",
        file_name: str = "",
        file_path: str = "",
        file_size_bytes: int | None = None,
        mime_type: str | None = None,
        notes: str | None = None,
        created_by: UUID | None = None,
    ) -> dict:
        self._check_authority(created_by, "update_supplier")
        supplier = await self._repository.get_by_id(supplier_id, legal_entity_id)
        if not supplier:
            raise SupplierNotFoundError(f"Supplier {supplier_id} not found")
        fields = {
            "document_type": document_type,
            "file_name": file_name,
            "file_path": file_path,
            "file_size_bytes": file_size_bytes,
            "mime_type": mime_type,
            "notes": notes,
            "uploaded_by": created_by,
        }
        result = await self._repository.add_attachment(supplier_id, **fields)
        self._record_audit(
            "add_attachment",
            {
                "supplier_id": str(supplier_id),
                "file_name": file_name,
                "created_by": str(created_by) if created_by else None,
            },
        )
        return result

    async def delete_attachment(
        self,
        supplier_id: UUID,
        attachment_id: UUID,
        deleted_by: UUID | None = None,
    ) -> bool:
        self._check_authority(deleted_by, "update_supplier")
        ok = await self._repository.delete_attachment(supplier_id, attachment_id)
        if ok:
            self._record_audit(
                "delete_attachment",
                {
                    "supplier_id": str(supplier_id),
                    "attachment_id": str(attachment_id),
                    "deleted_by": str(deleted_by) if deleted_by else None,
                },
            )
        return ok

    # ========================================================================
    # NOTES
    # ========================================================================

    async def list_notes(
        self, supplier_id: UUID, legal_entity_id: UUID
    ) -> list[dict]:
        supplier = await self._repository.get_by_id(supplier_id, legal_entity_id)
        if not supplier:
            raise SupplierNotFoundError(f"Supplier {supplier_id} not found")
        return await self._repository.list_notes(supplier_id)

    async def add_note(
        self,
        supplier_id: UUID,
        legal_entity_id: UUID,
        note: str,
        created_by: UUID | None = None,
    ) -> dict:
        self._check_authority(created_by, "update_supplier")
        supplier = await self._repository.get_by_id(supplier_id, legal_entity_id)
        if not supplier:
            raise SupplierNotFoundError(f"Supplier {supplier_id} not found")
        note = (note or "").strip()
        if not note:
            raise SupplierServiceError("Catatan tidak boleh kosong")
        result = await self._repository.add_note(
            supplier_id, note, created_by=created_by
        )
        self._record_audit(
            "add_note",
            {
                "supplier_id": str(supplier_id),
                "created_by": str(created_by) if created_by else None,
            },
        )
        return result

    async def delete_note(
        self,
        supplier_id: UUID,
        note_id: UUID,
        deleted_by: UUID | None = None,
    ) -> bool:
        self._check_authority(deleted_by, "update_supplier")
        ok = await self._repository.delete_note(supplier_id, note_id)
        if ok:
            self._record_audit(
                "delete_note",
                {
                    "supplier_id": str(supplier_id),
                    "note_id": str(note_id),
                    "deleted_by": str(deleted_by) if deleted_by else None,
                },
            )
        return ok

    # ========================================================================
    # ADDRESSES
    # ========================================================================

    async def list_addresses(
        self, supplier_id: UUID, legal_entity_id: UUID
    ) -> list[dict]:
        supplier = await self._repository.get_by_id(supplier_id, legal_entity_id)
        if not supplier:
            raise SupplierNotFoundError(f"Supplier {supplier_id} not found")
        return await self._repository.list_addresses(supplier_id)

    async def add_address(
        self, supplier_id: UUID, legal_entity_id: UUID, **fields
    ) -> dict:
        supplier = await self._repository.get_by_id(supplier_id, legal_entity_id)
        if not supplier:
            raise SupplierNotFoundError(f"Supplier {supplier_id} not found")
        return await self._repository.add_address(supplier_id, **fields)

    async def update_address(
        self, supplier_id: UUID, address_id: UUID, **fields
    ) -> dict:
        return await self._repository.update_address(
            supplier_id, address_id, **fields
        )

    async def delete_address(self, supplier_id: UUID, address_id: UUID) -> bool:
        return await self._repository.delete_address(supplier_id, address_id)

    # ========================================================================
    # CONTACTS
    # ========================================================================

    async def list_contacts(
        self, supplier_id: UUID, legal_entity_id: UUID
    ) -> list[dict]:
        supplier = await self._repository.get_by_id(supplier_id, legal_entity_id)
        if not supplier:
            raise SupplierNotFoundError(f"Supplier {supplier_id} not found")
        return await self._repository.list_contacts(supplier_id)

    async def add_contact(
        self, supplier_id: UUID, legal_entity_id: UUID, **fields
    ) -> dict:
        supplier = await self._repository.get_by_id(supplier_id, legal_entity_id)
        if not supplier:
            raise SupplierNotFoundError(f"Supplier {supplier_id} not found")
        return await self._repository.add_contact(supplier_id, **fields)

    async def update_contact(
        self, supplier_id: UUID, contact_id: UUID, **fields
    ) -> dict:
        return await self._repository.update_contact(
            supplier_id, contact_id, **fields
        )

    async def delete_contact(self, supplier_id: UUID, contact_id: UUID) -> bool:
        return await self._repository.delete_contact(supplier_id, contact_id)

    # ========================================================================
    # TAGS
    # ========================================================================

    async def list_tags(
        self, supplier_id: UUID, legal_entity_id: UUID
    ) -> list[dict]:
        supplier = await self._repository.get_by_id(supplier_id, legal_entity_id)
        if not supplier:
            raise SupplierNotFoundError(f"Supplier {supplier_id} not found")
        return await self._repository.list_tags(supplier_id)

    async def add_tag(
        self, supplier_id: UUID, legal_entity_id: UUID, tag: str
    ) -> dict:
        supplier = await self._repository.get_by_id(supplier_id, legal_entity_id)
        if not supplier:
            raise SupplierNotFoundError(f"Supplier {supplier_id} not found")
        tag = (tag or "").strip()
        if not tag:
            raise SupplierServiceError("Tag tidak boleh kosong")
        return await self._repository.add_tag(supplier_id, tag)

    async def remove_tag(self, supplier_id: UUID, tag_id: UUID) -> bool:
        return await self._repository.remove_tag(supplier_id, tag_id)

    # ========================================================================
    # CREDIT LIMIT
    # ========================================================================

    async def update_credit_limit(
        self,
        supplier_id: UUID,
        legal_entity_id: UUID,
        new_limit: Decimal,
        reason: str | None,
        updated_by: UUID | None,
    ) -> Supplier:
        self._check_authority(updated_by, "update_credit_limit")
        if new_limit < 0:
            raise SupplierServiceError("Limit kredit tidak boleh negatif")
        supplier = await self._repository.get_by_id(supplier_id, legal_entity_id)
        if not supplier:
            raise SupplierNotFoundError(f"Supplier {supplier_id} not found")

        old_limit = Decimal(str(supplier.credit_limit or 0))
        if old_limit == new_limit:
            return supplier

        supplier.credit_limit = new_limit
        supplier = await self._repository.update(supplier)

        # Catat riwayat perubahan limit
        try:
            await self._repository.add_credit_history(
                supplier_id=supplier_id,
                old_limit=old_limit,
                new_limit=new_limit,
                reason=reason,
                changed_by=updated_by,
            )
        except Exception as e:
            logger.warning(f"Gagal mencatat riwayat kredit: {e}")

        self._stats["suppliers_updated"] += 1
        if self._event_publisher:
            await self._publish_event(
                event_type="SupplierCreditLimitChanged",
                aggregate_id=supplier.id,
                payload={
                    "supplier_id": str(supplier.id),
                    "supplier_code": supplier.supplier_code,
                    "old_limit": str(old_limit),
                    "new_limit": str(new_limit),
                    "changed_by": str(updated_by) if updated_by else "system",
                },
            )
        self._record_audit(
            "update_credit_limit",
            {
                "supplier_id": str(supplier_id),
                "old_limit": str(old_limit),
                "new_limit": str(new_limit),
                "changed_by": str(updated_by) if updated_by else None,
            },
        )
        return supplier

    async def get_credit_history(
        self,
        supplier_id: UUID,
        legal_entity_id: UUID,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        supplier = await self._repository.get_by_id(supplier_id, legal_entity_id)
        if not supplier:
            raise SupplierNotFoundError(f"Supplier {supplier_id} not found")
        return await self._repository.list_credit_history(
            supplier_id, limit=limit, offset=offset
        )

    # ========================================================================
    # BALANCE HISTORY
    # ========================================================================

    async def get_balance_history(
        self,
        supplier_id: UUID,
        legal_entity_id: UUID,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        supplier = await self._repository.get_by_id(supplier_id, legal_entity_id)
        if not supplier:
            raise SupplierNotFoundError(f"Supplier {supplier_id} not found")
        return await self._repository.list_balance_history(
            supplier_id, limit=limit, offset=offset
        )

    # ========================================================================
    # STATS
    # ========================================================================

    def get_stats(self) -> dict[str, int]:
        return self._stats.copy()

    def get_audit_trail(self) -> list[dict[str, Any]]:
        return self._audit_trail.copy()


# ============================================================================
# Factory
# ============================================================================


async def create_supplier_service(
    repository: SupplierRepositoryPort,
    event_publisher: EventPublisherPort | None = None,
) -> SupplierService:
    return SupplierService(repository=repository, event_publisher=event_publisher)


__all__ = [
    "Supplier",
    "SupplierHasTransactionsError",
    "SupplierNotFoundError",
    "SupplierService",
    "SupplierServiceError",
    "SupplierStatus",
    "WithholdingCategory",
    "create_supplier_service",
]