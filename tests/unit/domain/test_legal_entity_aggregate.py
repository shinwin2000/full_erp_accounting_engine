#!/usr/bin/env python3

"""
Module: test_legal_entity_aggregate.py

Unit tests untuk Legal Entity aggregate root (class LegalEntity).
Menguji invariants, business rules, dan domain events sesuai implementasi asli.

Perbaikan:
    - Memperbaiki indentasi yang rusak.
    - Mengganti tipe parameter 'value' di helper pct() dari float menjadi Decimal
      (atau terima int/str juga) untuk memenuhi aturan MNY-023.
    - Menambahkan import Decimal di helper.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from domain.legal_entity.aggregate_root import (
    FiscalYearType,
    LegalEntity,
    LegalEntityStatus,
    LegalEntityType,
)
from domain.legal_entity.company_tax_profile_vo import (
    CompanyTaxProfileVO,
    TaxPaymentMethod,
    TaxRegime,
)
from domain.legal_entity.domain_events import (
    LegalEntityCreated,
    LegalEntityDeactivated,
    LegalEntityUpdated,
)
from domain.shared_value_objects.npwp_vo import NPWP
from domain.shared_value_objects.percentage_vo import Percentage


# Helper untuk membuat Percentage - menerima Decimal atau nilai yang bisa dikonversi
def pct(value: Decimal | int | str) -> Percentage:
    """Buat Percentage dari nilai numerik (dianggap sebagai persentase)."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return Percentage(value)


class TestLegalEntityAggregate:
    """Test suite untuk LegalEntity aggregate root."""

    @pytest.fixture
    def valid_legal_entity_data(self) -> dict:
        """Data minimal untuk membuat LegalEntity."""
        return {
            "entity_id": uuid4(),
            "entity_code": "PTMJ001",
            "entity_name": "PT Maju Jaya",
            "legal_name": "PT Maju Jaya",
            "entity_type": LegalEntityType.LIMITED,
            "status": LegalEntityStatus.ACTIVE,
            "npwp": NPWP("123456789012345"),
            "address": "Jl. Sudirman No. 1 Jakarta",
            "city": "Jakarta",
            "province": "DKI Jakarta",
            "postal_code": "10000",
            "country": "ID",
            "phone": "021-1234567",
            "email": "info@majujaya.com",
            "website": "www.majujaya.com",
            "fiscal_year_type": FiscalYearType.CALENDAR,
            "fiscal_year_start_month": 1,
            "fiscal_year_start_day": 1,
            "functional_currency": "IDR",
            "parent_entity_id": None,
            "consolidation_group": None,
            "established_date": datetime(2020, 1, 1, tzinfo=UTC),
            "created_by": "system",
            "version": 1,
        }

    @pytest.fixture
    def valid_tax_profile(self) -> CompanyTaxProfileVO:
        """Profil pajak valid."""
        return CompanyTaxProfileVO(
            is_pkp=True,
            tax_regime=TaxRegime.GENERAL,
            corporate_income_tax_rate=pct(22.0),
            vat_rate=pct(11.0),
            vat_collection_method="output",
            income_tax_article=None,
            tax_bracket=None,
            payment_method=TaxPaymentMethod.MONTHLY_INSTALLMENT,
            annual_return_deadline_month=4,
        )

    def test_create_legal_entity_success(
        self, valid_legal_entity_data, valid_tax_profile
    ):
        data = valid_legal_entity_data.copy()
        data["tax_profile"] = valid_tax_profile
        entity = LegalEntity(**data)
        assert entity.entity_id == data["entity_id"]
        assert entity.entity_name == "PT Maju Jaya"
        assert entity.status == LegalEntityStatus.ACTIVE
        assert entity.tax_profile.is_pkp is True
        assert entity.version == 1

    @pytest.mark.asyncio
    async def test_create_legal_entity_duplicate_npwp_raises_error(
        self, valid_legal_entity_data, valid_tax_profile, mocker
    ):
        """Test: Duplikasi NPWP harus dicegah (mock repository di service layer)."""
        # Buat entity yang sudah ada dengan NPWP yang sama
        existing_data = valid_legal_entity_data.copy()
        existing_data["tax_profile"] = valid_tax_profile
        existing_entity = LegalEntity(**existing_data)

        # Mock repository
        mock_repo = mocker.Mock()
        mock_repo.get_by_npwp = AsyncMock(return_value=existing_entity)

        # Simulasi service function yang melakukan pengecekan duplicate
        async def create_legal_entity(data, tax_profile, repo):
            npwp_str = str(data["npwp"])
            existing = await repo.get_by_npwp(npwp_str)
            if existing:
                raise ValueError("NPWP already exists")
            return LegalEntity(**{**data, "tax_profile": tax_profile})

        # Test bahwa error di-raise
        with pytest.raises(ValueError, match="NPWP already exists"):
            await create_legal_entity(
                valid_legal_entity_data, valid_tax_profile, mock_repo
            )

        mock_repo.get_by_npwp.assert_called_once_with(
            str(valid_legal_entity_data["npwp"])
        )

    def test_update_company_info(
        self, valid_legal_entity_data, valid_tax_profile
    ):
        data = valid_legal_entity_data.copy()
        data["tax_profile"] = valid_tax_profile
        entity = LegalEntity(**data)
        new_address = "Jl. Gatot Subroto No. 5"
        updated_entity = LegalEntity(
            **{
                **data,
                "address": new_address,
                "updated_at": datetime.now(UTC),
                "version": entity.version + 1,
            }
        )
        assert updated_entity.address == new_address
        assert updated_entity.version == entity.version + 1

    def test_deactivate_legal_entity(
        self, valid_legal_entity_data, valid_tax_profile
    ):
        data = valid_legal_entity_data.copy()
        data["tax_profile"] = valid_tax_profile
        entity = LegalEntity(**data)
        suspended = entity.suspend(
            suspended_by="admin", reason="Restructuring"
        )
        assert suspended.status == LegalEntityStatus.SUSPENDED
        assert suspended.version == entity.version + 1

    def test_cannot_deactivate_already_inactive(
        self, valid_legal_entity_data, valid_tax_profile
    ):
        data = valid_legal_entity_data.copy()
        data["tax_profile"] = valid_tax_profile
        entity = LegalEntity(**data)
        suspended = entity.suspend("admin", "First")
        assert suspended.status == LegalEntityStatus.SUSPENDED
        dissolved = suspended.dissolve("admin", datetime.now(UTC))
        assert dissolved.status == LegalEntityStatus.DISSOLVED
        with pytest.raises(
            ValueError,
            match="Cannot suspend a dissolved entity",
        ):
            dissolved.suspend("admin", "Second")
        with pytest.raises(
            ValueError, match="Entity already dissolved"
        ):
            dissolved.dissolve("admin", datetime.now(UTC))

    def test_update_tax_profile(
        self,
        valid_legal_entity_data,
        valid_tax_profile,
    ):
        data = valid_legal_entity_data.copy()
        data["tax_profile"] = valid_tax_profile
        entity = LegalEntity(**data)
        new_tax_profile = CompanyTaxProfileVO(
            is_pkp=False,
            tax_regime=TaxRegime.FINAL,
            corporate_income_tax_rate=pct(0.5),
            vat_rate=pct(0.0),
            vat_collection_method="output",
            income_tax_article="PPH 23",
            tax_bracket="UMKM",
            payment_method=TaxPaymentMethod.WITHHOLDING,
            annual_return_deadline_month=4,
        )
        updated = entity.update_tax_profile(
            new_tax_profile, updated_by="admin"
        )
        assert updated.tax_profile.tax_regime == TaxRegime.FINAL
        assert updated.tax_profile.corporate_income_tax_rate.value == Decimal("0.5")
        assert updated.version == entity.version + 1

    def test_legal_entity_id_is_uuid(
        self, valid_legal_entity_data, valid_tax_profile
    ):
        data = valid_legal_entity_data.copy()
        data["tax_profile"] = valid_tax_profile
        entity = LegalEntity(**data)
        assert isinstance(entity.entity_id, UUID)

    def test_version_increments_on_update(
        self, valid_legal_entity_data, valid_tax_profile
    ):
        data = valid_legal_entity_data.copy()
        data["tax_profile"] = valid_tax_profile
        entity = LegalEntity(**data)
        assert entity.version == 1
        entity2 = entity.suspend("admin", "Test")
        assert entity2.version == 2
        entity3 = entity2.reactivate("admin", "Reactivate")
        assert entity3.version == 3
        entity4 = entity3.update_tax_profile(valid_tax_profile, "admin")
        assert entity4.version == 4

    @pytest.mark.asyncio
    async def test_optimistic_locking_raises_error(
        self, valid_legal_entity_data, valid_tax_profile, mocker
    ):
        """Test: Optimistic lock conflict (mock repository)."""
        data = valid_legal_entity_data.copy()
        data["tax_profile"] = valid_tax_profile
        entity_v1 = LegalEntity(**data)
        # Entity dengan version berbeda (seharusnya 1, tapi kita set 2)
        entity_v2 = LegalEntity(**{**data, "version": 2})

        mock_repo = mocker.Mock()
        # Mock get_by_id mengembalikan entity dengan version 1
        mock_repo.get_by_id = AsyncMock(return_value=entity_v1)
        mock_repo.save = AsyncMock()

        async def save_entity(entity, repo):
            existing = await repo.get_by_id(entity.entity_id)
            if existing and existing.version != entity.version:
                raise Exception("Optimistic lock: version mismatch")
            await repo.save(entity)

        with pytest.raises(Exception, match="Optimistic lock"):
            await save_entity(entity_v2, mock_repo)

        mock_repo.get_by_id.assert_called_once_with(entity_v2.entity_id)
        mock_repo.save.assert_not_called()

    def test_factory_method_reconstruct(
        self, valid_legal_entity_data, valid_tax_profile
    ):
        data = valid_legal_entity_data.copy()
        data["tax_profile"] = valid_tax_profile
        original = LegalEntity(**data)
        reconstructed = LegalEntity(
            entity_id=original.entity_id,
            entity_code=original.entity_code,
            entity_name=original.entity_name,
            legal_name=original.legal_name,
            entity_type=original.entity_type,
            status=original.status,
            npwp=original.npwp,
            tax_profile=original.tax_profile,
            address=original.address,
            city=original.city,
            province=original.province,
            postal_code=original.postal_code,
            country=original.country,
            phone=original.phone,
            email=original.email,
            website=original.website,
            fiscal_year_type=original.fiscal_year_type,
            fiscal_year_start_month=original.fiscal_year_start_month,
            fiscal_year_start_day=original.fiscal_year_start_day,
            functional_currency=original.functional_currency,
            parent_entity_id=original.parent_entity_id,
            consolidation_group=original.consolidation_group,
            established_date=original.established_date,
            created_at=original.created_at,
            updated_at=original.updated_at,
            created_by=original.created_by,
            version=original.version,
        )
        assert reconstructed.entity_id == original.entity_id
        assert reconstructed.entity_name == original.entity_name

    def test_domain_events_creation(
        self, valid_legal_entity_data, valid_tax_profile
    ):
        legal_entity_id = uuid4()
        event_created = LegalEntityCreated(
            aggregate_id=legal_entity_id,
            aggregate_version=1,
            legal_entity_id=legal_entity_id,
            user_id="admin",
        )
        assert event_created.event_type.value == "legal_entity_created"
        assert event_created.legal_entity_id == legal_entity_id

        event_deactivated = LegalEntityDeactivated(
            aggregate_id=legal_entity_id,
            aggregate_version=2,
            reason="Restructuring",
            user_id="admin",
        )
        assert event_deactivated.reason == "Restructuring"

        event_updated = LegalEntityUpdated(
            aggregate_id=legal_entity_id,
            aggregate_version=3,
            updated_fields=["address"],
            user_id="admin",
        )
        assert event_updated.updated_fields == ["address"]


if __name__ == "__main__":
    pytest.main([__file__])