# test_company_entity.py
# Comprehensive tests for company_entity.py

from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from domain.legal_entity.company_entity import (
    CompanyEntity,
    CompanyEntityRepository,
    LegalEntityStatus,
    LegalEntityType,
)
from domain.shared_value_objects.npwp_vo import NPWP

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def valid_npwp():
    """Return a valid NPWP."""
    return NPWP("123456789012345")


@pytest.fixture
def valid_company_data(valid_npwp):
    """Return base data for a valid company."""
    return {
        "company_id": uuid4(),
        "legal_entity_id": uuid4(),
        "trade_name": "PT Maju Jaya",
        "legal_name": "PT Maju Jaya Tbk",
        "entity_type": LegalEntityType.CORPORATION,
        "npwp": valid_npwp,
        "address": "Jl. Sudirman No. 10",
        "city": "Jakarta Selatan",
        "province": "DKI Jakarta",
        "postal_code": "10220",
        "country": "Indonesia",
        "phone": "021-12345678",
        "email": "info@majujaya.co.id",
        "website": "https://majujaya.co.id",
        "established_date": datetime(2010, 1, 1, 0, 0, 0, tzinfo=UTC),
        "business_license_number": "12345/SIUP/2020",
        "business_license_date": datetime(2020, 6, 1, 0, 0, 0, tzinfo=UTC),
        "pkp_status": False,
        "pkp_registration_date": None,
        "created_at": datetime(2025, 1, 1, 8, 0, 0, tzinfo=UTC),
        "updated_at": datetime(2025, 1, 1, 8, 0, 0, tzinfo=UTC),
        "version": 1,
    }


@pytest.fixture
def valid_company(valid_company_data):
    """Create a valid CompanyEntity."""
    return CompanyEntity(**valid_company_data)


# ============================================================================
# Tests for Enums
# ============================================================================

class TestLegalEntityType:
    def test_members(self):
        assert LegalEntityType.CORPORATION.value == "corporation"
        assert LegalEntityType.LIMITED.value == "limited"
        assert LegalEntityType.SOLE_PROPRIETORSHIP.value == "sole"
        assert LegalEntityType.PARTNERSHIP.value == "partnership"
        assert LegalEntityType.COOPERATIVE.value == "cooperative"
        assert LegalEntityType.NON_PROFIT.value == "non_profit"
        assert LegalEntityType.GOVERNMENT.value == "government"


class TestLegalEntityStatus:
    def test_members(self):
        assert LegalEntityStatus.ACTIVE.value == "active"
        assert LegalEntityStatus.INACTIVE.value == "inactive"
        assert LegalEntityStatus.SUSPENDED.value == "suspended"
        assert LegalEntityStatus.DISSOLVED.value == "dissolved"


# ============================================================================
# Tests for CompanyEntity - Construction and Validation
# ============================================================================

class TestCompanyEntityConstruction:
    def test_construction_valid(self, valid_company):
        assert valid_company.trade_name == "PT Maju Jaya"
        assert valid_company.legal_name == "PT Maju Jaya Tbk"
        assert valid_company.entity_type == LegalEntityType.CORPORATION
        assert valid_company.npwp is not None
        assert valid_company.address == "Jl. Sudirman No. 10"
        assert valid_company.pkp_status is False
        assert valid_company.version == 1

    def test_validation_trade_name_too_short(self, valid_npwp):
        with pytest.raises(ValueError, match="Trade name must be at least 2 characters"):
            CompanyEntity(
                company_id=uuid4(),
                legal_entity_id=uuid4(),
                trade_name="A",
                legal_name="PT Contoh",
                entity_type=LegalEntityType.CORPORATION,
                npwp=valid_npwp,
                address="Jl. Merdeka No. 1",
                city="Jakarta",
                province="DKI Jakarta",
                postal_code="10110",
                country="Indonesia",
            )

    def test_validation_legal_name_too_short(self, valid_npwp):
        with pytest.raises(ValueError, match="Legal name must be at least 2 characters"):
            CompanyEntity(
                company_id=uuid4(),
                legal_entity_id=uuid4(),
                trade_name="PT Contoh",
                legal_name="A",
                entity_type=LegalEntityType.CORPORATION,
                npwp=valid_npwp,
                address="Jl. Merdeka No. 1",
                city="Jakarta",
                province="DKI Jakarta",
                postal_code="10110",
                country="Indonesia",
            )

    def test_validation_address_too_short(self, valid_npwp):
        with pytest.raises(ValueError, match="Address must be at least 5 characters"):
            CompanyEntity(
                company_id=uuid4(),
                legal_entity_id=uuid4(),
                trade_name="PT Contoh",
                legal_name="PT Contoh Jaya",
                entity_type=LegalEntityType.CORPORATION,
                npwp=valid_npwp,
                address="Jl.",
                city="Jakarta",
                province="DKI Jakarta",
                postal_code="10110",
                country="Indonesia",
            )

    def test_validation_city_too_short(self, valid_npwp):
        with pytest.raises(ValueError, match="City must be at least 2 characters"):
            CompanyEntity(
                company_id=uuid4(),
                legal_entity_id=uuid4(),
                trade_name="PT Contoh",
                legal_name="PT Contoh Jaya",
                entity_type=LegalEntityType.CORPORATION,
                npwp=valid_npwp,
                address="Jl. Merdeka No. 1",
                city="J",
                province="DKI Jakarta",
                postal_code="10110",
                country="Indonesia",
            )

    def test_validation_province_too_short(self, valid_npwp):
        with pytest.raises(ValueError, match="Province must be at least 2 characters"):
            CompanyEntity(
                company_id=uuid4(),
                legal_entity_id=uuid4(),
                trade_name="PT Contoh",
                legal_name="PT Contoh Jaya",
                entity_type=LegalEntityType.CORPORATION,
                npwp=valid_npwp,
                address="Jl. Merdeka No. 1",
                city="Jakarta",
                province="D",
                postal_code="10110",
                country="Indonesia",
            )

    def test_validation_version(self, valid_npwp):
        with pytest.raises(ValueError, match="Version must be >= 1"):
            CompanyEntity(
                company_id=uuid4(),
                legal_entity_id=uuid4(),
                trade_name="PT Contoh",
                legal_name="PT Contoh Jaya",
                entity_type=LegalEntityType.CORPORATION,
                npwp=valid_npwp,
                address="Jl. Merdeka No. 1",
                city="Jakarta",
                province="DKI Jakarta",
                postal_code="10110",
                country="Indonesia",
                version=0,
            )


# ============================================================================
# Tests for Business Methods
# ============================================================================

class TestCompanyEntityMethods:
    def test_update_address(self, valid_company):
        new_address = "Jl. Thamrin No. 20"
        new_city = "Jakarta Pusat"
        new_province = "DKI Jakarta"
        new_postal = "10350"
        new_country = "Indonesia"
        updated = valid_company.update_address(
            address=new_address,
            city=new_city,
            province=new_province,
            postal_code=new_postal,
            country=new_country,
            updated_by="admin",
        )
        assert updated.address == new_address
        assert updated.city == new_city
        assert updated.province == new_province
        assert updated.postal_code == new_postal
        assert updated.country == new_country
        assert updated.version == valid_company.version + 1
        assert updated.updated_at > valid_company.updated_at
        # Other fields should remain unchanged
        assert updated.trade_name == valid_company.trade_name
        assert updated.legal_name == valid_company.legal_name
        assert updated.npwp == valid_company.npwp

    def test_update_contact(self, valid_company):
        new_phone = "021-87654321"
        new_email = "contact@majujaya.co.id"
        new_website = "https://www.majujaya.co.id"
        updated = valid_company.update_contact(
            phone=new_phone,
            email=new_email,
            website=new_website,
            updated_by="admin",
        )
        assert updated.phone == new_phone
        assert updated.email == new_email
        assert updated.website == new_website
        assert updated.version == valid_company.version + 1
        assert updated.updated_at > valid_company.updated_at

    def test_update_contact_none_values(self, valid_company):
        updated = valid_company.update_contact(
            phone=None,
            email=None,
            website=None,
            updated_by="admin",
        )
        assert updated.phone is None
        assert updated.email is None
        assert updated.website is None
        assert updated.version == valid_company.version + 1

    def test_register_pkp(self, valid_company):
        reg_date = datetime(2025, 2, 1, 12, 0, 0, tzinfo=UTC)
        updated = valid_company.register_pkp(registration_date=reg_date, registered_by="tax_agent")
        assert updated.pkp_status is True
        assert updated.pkp_registration_date == reg_date
        assert updated.version == valid_company.version + 1
        assert updated.updated_at > valid_company.updated_at

    def test_register_pkp_already_pkp(self, valid_company):
        # First register as PKP
        reg_date = datetime(2025, 2, 1, 12, 0, 0, tzinfo=UTC)
        pkp_company = valid_company.register_pkp(reg_date, "tax_agent")
        # Register again should still set pkp_status=True (no change)
        new_date = datetime(2025, 3, 1, 12, 0, 0, tzinfo=UTC)
        updated = pkp_company.register_pkp(new_date, "tax_agent")
        assert updated.pkp_status is True
        # The date should be updated to the new date (business rule: latest registration date)
        assert updated.pkp_registration_date == new_date
        assert updated.version == pkp_company.version + 1

    def test_is_pkp(self, valid_company):
        assert valid_company.is_pkp() is False
        pkp = valid_company.register_pkp(datetime.now(UTC), "admin")
        assert pkp.is_pkp() is True


# ============================================================================
# Tests for Serialization
# ============================================================================

class TestCompanyEntitySerialization:
    def test_to_dict(self, valid_company):
        d = valid_company.to_dict()
        assert d["company_id"] == str(valid_company.company_id)
        assert d["legal_entity_id"] == str(valid_company.legal_entity_id)
        assert d["trade_name"] == "PT Maju Jaya"
        assert d["legal_name"] == "PT Maju Jaya Tbk"
        assert d["entity_type"] == "corporation"
        assert d["npwp"] == str(valid_company.npwp)
        assert d["address"] == "Jl. Sudirman No. 10"
        assert d["city"] == "Jakarta Selatan"
        assert d["province"] == "DKI Jakarta"
        assert d["postal_code"] == "10220"
        assert d["country"] == "Indonesia"
        assert d["phone"] == "021-12345678"
        assert d["email"] == "info@majujaya.co.id"
        assert d["website"] == "https://majujaya.co.id"
        assert d["established_date"] == "2010-01-01T00:00:00+00:00"
        assert d["business_license_number"] == "12345/SIUP/2020"
        assert d["pkp_status"] is False
        assert d["pkp_registration_date"] is None
        assert d["version"] == 1
        assert "created_at" in d
        assert "updated_at" in d

    def test_to_dict_with_pkp(self, valid_company):
        pkp = valid_company.register_pkp(datetime(2025, 2, 1, 12, 0, 0, tzinfo=UTC), "admin")
        d = pkp.to_dict()
        assert d["pkp_status"] is True
        assert d["pkp_registration_date"] == "2025-02-01T12:00:00+00:00"


# ============================================================================
# Tests for Repository (abstract)
# ============================================================================

class TestCompanyEntityRepository:
    def test_abstract_methods_raise(self):
        repo = CompanyEntityRepository()
        with pytest.raises(NotImplementedError):
            repo.get_by_id(uuid4())
        with pytest.raises(NotImplementedError):
            repo.get_by_legal_entity(uuid4())
        with pytest.raises(NotImplementedError):
            repo.get_by_npwp("123456789012345")
        with pytest.raises(NotImplementedError):
            repo.save(MagicMock())
        with pytest.raises(NotImplementedError):
            repo.delete(uuid4())
