# tests/policy_engine/psak/test_psak_67_interests_in_other_entities.py
"""
Comprehensive tests for PSAK 67: Interests in Other Entities.
Covers all methods including aggregations, validation, and add operations.
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from policy_engine.psak.psak_67_interests_in_other_entities import (
    PSAK67ComplianceLevel,
    PSAK67ControlAssessment,
    PSAK67InterestsDisclosure,
    PSAK67InterestService,
    PSAK67NCIChoice,
    PSAK67NonControllingInterest,
    PSAK67OwnershipInterest,
    PSAK67RelationshipType,
    PSAK67RiskType,
    PSAK67Rules,
    PSAK67SignificantRestriction,
    PSAK67StructuredEntity,
    PSAK67ValidationResult,
    PSAK67Validator,
    get_psak67_validator,
)


# ============================================================================
# Enum tests (same as before but with better assertions)
# ============================================================================

class TestPSAK67RelationshipType:
    def test_members_exist(self):
        assert hasattr(PSAK67RelationshipType, 'SUBSIDIARY')
        assert hasattr(PSAK67RelationshipType, 'JOINT_VENTURE')
        assert hasattr(PSAK67RelationshipType, 'ASSOCIATE')
        assert hasattr(PSAK67RelationshipType, 'STRUCTURED_ENTITY')
        assert PSAK67RelationshipType.SUBSIDIARY.value == "anak_perusahaan"
        assert PSAK67RelationshipType.JOINT_VENTURE.value == "ventura_bersama"
        assert PSAK67RelationshipType.ASSOCIATE.value == "asosiasi"
        assert PSAK67RelationshipType.STRUCTURED_ENTITY.value == "entitas_terstruktur"


class TestPSAK67NCIChoice:
    def test_members_exist(self):
        assert hasattr(PSAK67NCIChoice, 'PROPORTIONATE_SHARE')
        assert hasattr(PSAK67NCIChoice, 'FAIR_VALUE')
        assert PSAK67NCIChoice.PROPORTIONATE_SHARE.value == "proporsi_aset_bersih"
        assert PSAK67NCIChoice.FAIR_VALUE.value == "nilai_wajar"


class TestPSAK67ControlAssessment:
    def test_members_exist(self):
        assert hasattr(PSAK67ControlAssessment, 'CONTROL')
        assert hasattr(PSAK67ControlAssessment, 'JOINT_CONTROL')
        assert hasattr(PSAK67ControlAssessment, 'SIGNIFICANT_INFLUENCE')
        assert hasattr(PSAK67ControlAssessment, 'NO_CONTROL')
        assert PSAK67ControlAssessment.CONTROL.value == "pengendalian"
        assert PSAK67ControlAssessment.JOINT_CONTROL.value == "pengendalian_bersama"
        assert PSAK67ControlAssessment.SIGNIFICANT_INFLUENCE.value == "pengaruh_signifikan"
        assert PSAK67ControlAssessment.NO_CONTROL.value == "tidak_ada_pengendalian"


class TestPSAK67RiskType:
    def test_members_exist(self):
        assert hasattr(PSAK67RiskType, 'EXPOSURE_TO_LOSS')
        assert hasattr(PSAK67RiskType, 'FUNDING_COMMITMENT')
        assert hasattr(PSAK67RiskType, 'CONTINGENT_LIABILITY')
        assert hasattr(PSAK67RiskType, 'OTHER')
        assert PSAK67RiskType.EXPOSURE_TO_LOSS.value == "eksposur_kerugian"
        assert PSAK67RiskType.FUNDING_COMMITMENT.value == "komitmen_pendanaan"
        assert PSAK67RiskType.CONTINGENT_LIABILITY.value == "liabilitas_kontinjensi"
        assert PSAK67RiskType.OTHER.value == "lainnya"


class TestPSAK67ComplianceLevel:
    def test_members_exist(self):
        assert hasattr(PSAK67ComplianceLevel, 'FULL')
        assert hasattr(PSAK67ComplianceLevel, 'SUBSTANTIAL')
        assert hasattr(PSAK67ComplianceLevel, 'PARTIAL')
        assert hasattr(PSAK67ComplianceLevel, 'NON_COMPLIANT')
        assert PSAK67ComplianceLevel.FULL.value == "penuh"
        assert PSAK67ComplianceLevel.SUBSTANTIAL.value == "substansial"
        assert PSAK67ComplianceLevel.PARTIAL.value == "sebagian"
        assert PSAK67ComplianceLevel.NON_COMPLIANT.value == "tidak_patuh"


# ============================================================================
# Data classes - construction and method tests
# ============================================================================

class TestPSAK67OwnershipInterest:
    def test_construction(self):
        ownership_id = uuid4()
        investee_id = uuid4()
        acquisition_date = datetime.now(UTC)
        oi = PSAK67OwnershipInterest(
            ownership_id=ownership_id,
            investee_id=investee_id,
            investee_name="PT Anak",
            relationship_type=PSAK67RelationshipType.SUBSIDIARY,
            ownership_percentage=Decimal("80"),
            voting_percentage=Decimal("80"),
            acquisition_date=acquisition_date,
            control_assessment=PSAK67ControlAssessment.CONTROL,
            notes="Test"
        )
        assert oi.ownership_id == ownership_id
        assert oi.investee_id == investee_id
        assert oi.investee_name == "PT Anak"
        assert oi.relationship_type == PSAK67RelationshipType.SUBSIDIARY
        assert oi.ownership_percentage == Decimal("80")
        assert oi.voting_percentage == Decimal("80")
        assert oi.acquisition_date == acquisition_date
        assert oi.control_assessment == PSAK67ControlAssessment.CONTROL
        assert oi.notes == "Test"

    def test_to_dict(self):
        oi = PSAK67OwnershipInterest(
            ownership_id=uuid4(),
            investee_id=uuid4(),
            investee_name="PT Anak",
            relationship_type=PSAK67RelationshipType.SUBSIDIARY,
            ownership_percentage=Decimal("80"),
            voting_percentage=Decimal("80"),
            acquisition_date=datetime(2020, 1, 1, tzinfo=UTC),
        )
        d = oi.to_dict()
        assert "investee_id" in d
        assert d["investee_name"] == "PT Anak"
        assert d["relationship"] == "anak_perusahaan"
        assert d["ownership"] == "80"
        assert d["voting"] == "80"
        assert d["acquisition_date"] == "2020-01-01T00:00:00+00:00"
        assert d["control_assessment"] == "pengendalian"


class TestPSAK67NonControllingInterest:
    def test_construction(self):
        nci_id = uuid4()
        subsidiary_id = uuid4()
        nci = PSAK67NonControllingInterest(
            nci_id=nci_id,
            subsidiary_id=subsidiary_id,
            subsidiary_name="PT Anak",
            nci_percentage=Decimal("20"),
            nci_measurement=PSAK67NCIChoice.PROPORTIONATE_SHARE,
            nci_amount=Decimal("1000000"),
            profit_allocated_to_nci=Decimal("200000"),
            dividends_paid_to_nci=Decimal("50000"),
            other_comprehensive_income_allocated=Decimal("10000"),
        )
        assert nci.nci_id == nci_id
        assert nci.subsidiary_id == subsidiary_id
        assert nci.nci_percentage == Decimal("20")
        assert nci.nci_amount == Decimal("1000000")
        assert nci.profit_allocated_to_nci == Decimal("200000")

    def test_to_dict(self):
        nci = PSAK67NonControllingInterest(
            nci_id=uuid4(),
            subsidiary_id=uuid4(),
            subsidiary_name="PT Anak",
            nci_percentage=Decimal("20"),
            nci_measurement=PSAK67NCIChoice.PROPORTIONATE_SHARE,
            nci_amount=Decimal("1000000"),
        )
        d = nci.to_dict()
        assert d["subsidiary"] == "PT Anak"
        assert d["nci_percentage"] == "20"
        assert d["measurement"] == "proporsi_aset_bersih"
        assert d["nci_amount"] == "1000000"


class TestPSAK67StructuredEntity:
    def test_construction(self):
        entity_id = uuid4()
        se = PSAK67StructuredEntity(
            entity_id=entity_id,
            entity_name="Dana XYZ",
            nature_of_relationship="Investasi variabel",
            carrying_amount_assets=Decimal("5000000"),
            carrying_amount_liabilities=Decimal("4500000"),
            maximum_exposure_to_loss=Decimal("500000"),
            funding_commitments=Decimal("100000"),
            liquidity_agreements="Komitmen likuiditas",
        )
        assert se.entity_id == entity_id
        assert se.entity_name == "Dana XYZ"
        assert se.carrying_amount_assets == Decimal("5000000")
        assert se.maximum_exposure_to_loss == Decimal("500000")

    def test_to_dict(self):
        se = PSAK67StructuredEntity(
            entity_id=uuid4(),
            entity_name="Dana XYZ",
            nature_of_relationship="Investasi variabel",
            carrying_amount_assets=Decimal("5000000"),
            carrying_amount_liabilities=Decimal("4500000"),
            maximum_exposure_to_loss=Decimal("500000"),
            funding_commitments=Decimal("100000"),
        )
        d = se.to_dict()
        assert d["entity_name"] == "Dana XYZ"
        assert d["nature"] == "Investasi variabel"
        assert d["assets"] == "5000000"
        assert d["liabilities"] == "4500000"
        assert d["max_loss_exposure"] == "500000"
        assert d["funding_commitments"] == "100000"


class TestPSAK67SignificantRestriction:
    def test_construction(self):
        restriction_id = uuid4()
        investee_id = uuid4()
        r = PSAK67SignificantRestriction(
            restriction_id=restriction_id,
            investee_id=investee_id,
            investee_name="PT Anak",
            restriction_description="Tidak boleh bagi dividen",
            affected_assets="Laba ditahan",
            restricted_amount=Decimal("200000000"),
        )
        assert r.restriction_id == restriction_id
        assert r.investee_id == investee_id
        assert r.restricted_amount == Decimal("200000000")

    def test_to_dict(self):
        r = PSAK67SignificantRestriction(
            restriction_id=uuid4(),
            investee_id=uuid4(),
            investee_name="PT Anak",
            restriction_description="Tidak boleh bagi dividen",
            affected_assets="Laba ditahan",
            restricted_amount=Decimal("200000000"),
        )
        d = r.to_dict()
        assert d["investee"] == "PT Anak"
        assert d["restriction"] == "Tidak boleh bagi dividen"
        assert d["affected_assets"] == "Laba ditahan"
        assert d["amount"] == "200000000"


# ============================================================================
# PSAK67InterestsDisclosure - test aggregation methods
# ============================================================================

class TestPSAK67InterestsDisclosure:
    def test_total_nci_amount(self):
        nci1 = PSAK67NonControllingInterest(
            nci_id=uuid4(),
            subsidiary_id=uuid4(),
            subsidiary_name="A",
            nci_percentage=Decimal("20"),
            nci_measurement=PSAK67NCIChoice.PROPORTIONATE_SHARE,
            nci_amount=Decimal("1000000"),
        )
        nci2 = PSAK67NonControllingInterest(
            nci_id=uuid4(),
            subsidiary_id=uuid4(),
            subsidiary_name="B",
            nci_percentage=Decimal("30"),
            nci_measurement=PSAK67NCIChoice.PROPORTIONATE_SHARE,
            nci_amount=Decimal("2000000"),
        )
        disclosure = PSAK67InterestsDisclosure(
            disclosure_id=uuid4(),
            entity_id=uuid4(),
            entity_name="Induk",
            reporting_date=datetime.now(UTC),
            non_controlling_interests=[nci1, nci2],
        )
        assert disclosure.total_nci_amount() == Decimal("3000000")

    def test_total_structured_entity_assets(self):
        se1 = PSAK67StructuredEntity(
            entity_id=uuid4(),
            entity_name="SE1",
            nature_of_relationship="Test",
            carrying_amount_assets=Decimal("5000000"),
        )
        se2 = PSAK67StructuredEntity(
            entity_id=uuid4(),
            entity_name="SE2",
            nature_of_relationship="Test",
            carrying_amount_assets=Decimal("3000000"),
        )
        disclosure = PSAK67InterestsDisclosure(
            disclosure_id=uuid4(),
            entity_id=uuid4(),
            entity_name="Induk",
            reporting_date=datetime.now(UTC),
            structured_entities=[se1, se2],
        )
        assert disclosure.total_structured_entity_assets() == Decimal("8000000")

    def test_total_commitments_to_structured_entities(self):
        se1 = PSAK67StructuredEntity(
            entity_id=uuid4(),
            entity_name="SE1",
            nature_of_relationship="Test",
            funding_commitments=Decimal("100000"),
        )
        se2 = PSAK67StructuredEntity(
            entity_id=uuid4(),
            entity_name="SE2",
            nature_of_relationship="Test",
            funding_commitments=Decimal("200000"),
        )
        disclosure = PSAK67InterestsDisclosure(
            disclosure_id=uuid4(),
            entity_id=uuid4(),
            entity_name="Induk",
            reporting_date=datetime.now(UTC),
            structured_entities=[se1, se2],
        )
        assert disclosure.total_commitments_to_structured_entities() == Decimal("300000")

    def test_to_dict_includes_aggregates(self):
        nci = PSAK67NonControllingInterest(
            nci_id=uuid4(),
            subsidiary_id=uuid4(),
            subsidiary_name="A",
            nci_percentage=Decimal("20"),
            nci_measurement=PSAK67NCIChoice.PROPORTIONATE_SHARE,
            nci_amount=Decimal("1000000"),
        )
        se = PSAK67StructuredEntity(
            entity_id=uuid4(),
            entity_name="SE1",
            nature_of_relationship="Test",
            carrying_amount_assets=Decimal("5000000"),
            funding_commitments=Decimal("100000"),
        )
        disclosure = PSAK67InterestsDisclosure(
            disclosure_id=uuid4(),
            entity_id=uuid4(),
            entity_name="Induk",
            reporting_date=datetime(2026, 12, 31, tzinfo=UTC),
            non_controlling_interests=[nci],
            structured_entities=[se],
        )
        d = disclosure.to_dict()
        assert d["total_nci"] == "1000000"
        assert d["total_structured_assets"] == "5000000"
        assert d["total_commitments_structured"] == "100000"
        assert "ownership_interests" in d
        assert "non_controlling_interests" in d
        assert "structured_entities" in d
        assert "restrictions" in d
        assert "risks" in d


# ============================================================================
# PSAK67ValidationResult - test add_warning and add_error
# ============================================================================

class TestPSAK67ValidationResult:
    def test_add_warning_lowers_compliance_from_full(self):
        result = PSAK67ValidationResult(is_compliant=True, compliance_level=PSAK67ComplianceLevel.FULL)
        result.add_warning("Test warning")
        assert result.warnings == ["Test warning"]
        assert result.is_compliant is True  # warnings don't affect is_compliant
        assert result.compliance_level == PSAK67ComplianceLevel.SUBSTANTIAL

    def test_add_warning_does_not_change_from_substantial(self):
        result = PSAK67ValidationResult(is_compliant=True, compliance_level=PSAK67ComplianceLevel.SUBSTANTIAL)
        result.add_warning("Another warning")
        assert result.compliance_level == PSAK67ComplianceLevel.SUBSTANTIAL  # remains

    def test_add_error_sets_non_compliant(self):
        result = PSAK67ValidationResult(is_compliant=True, compliance_level=PSAK67ComplianceLevel.FULL)
        result.add_error("Critical error")
        assert result.errors == ["Critical error"]
        assert result.is_compliant is False
        assert result.compliance_level == PSAK67ComplianceLevel.NON_COMPLIANT

    def test_hash_computation(self):
        result1 = PSAK67ValidationResult(is_compliant=True, compliance_level=PSAK67ComplianceLevel.FULL)
        result2 = PSAK67ValidationResult(is_compliant=True, compliance_level=PSAK67ComplianceLevel.FULL)
        assert result1.hash_sha256 == result2.hash_sha256
        # Changing content changes hash
        result1.add_warning("x")
        result2.add_error("y")
        assert result1.hash_sha256 != result2.hash_sha256

    def test_to_dict(self):
        result = PSAK67ValidationResult(is_compliant=False, compliance_level=PSAK67ComplianceLevel.PARTIAL)
        result.add_error("Error1")
        result.add_warning("Warning1")
        d = result.to_dict()
        assert d["is_compliant"] is False
        assert d["compliance_level"] == "sebagian"
        assert d["errors"] == ["Error1"]
        assert d["warnings"] == ["Warning1"]
        assert "hash" in d


# ============================================================================
# PSAK67InterestService - functional tests
# ============================================================================

class TestPSAK67InterestService:
    def test_assess_control_control(self):
        result = PSAK67InterestService.assess_control(
            ownership_percentage=Decimal("60"),
            voting_percentage=Decimal("55"),
            has_contractual_control=True,
            has_power_over_key_decisions=False,
        )
        assert result == PSAK67ControlAssessment.CONTROL

    def test_assess_control_joint_control(self):
        result = PSAK67InterestService.assess_control(
            ownership_percentage=Decimal("30"),
            voting_percentage=Decimal("30"),
            has_contractual_control=False,
            has_power_over_key_decisions=True,
        )
        assert result == PSAK67ControlAssessment.JOINT_CONTROL

    def test_assess_control_significant_influence(self):
        result = PSAK67InterestService.assess_control(
            ownership_percentage=Decimal("25"),
            voting_percentage=Decimal("25"),
            has_contractual_control=False,
            has_power_over_key_decisions=False,
        )
        assert result == PSAK67ControlAssessment.SIGNIFICANT_INFLUENCE

    def test_assess_control_no_control(self):
        result = PSAK67InterestService.assess_control(
            ownership_percentage=Decimal("10"),
            voting_percentage=Decimal("10"),
            has_contractual_control=False,
            has_power_over_key_decisions=False,
        )
        assert result == PSAK67ControlAssessment.NO_CONTROL

    def test_is_structured_entity_true(self):
        assert PSAK67InterestService.is_structured_entity(voting_rights_exist=False, independent_powers=True) is True
        assert PSAK67InterestService.is_structured_entity(voting_rights_exist=True, independent_powers=False) is True

    def test_is_structured_entity_false(self):
        assert PSAK67InterestService.is_structured_entity(voting_rights_exist=True, independent_powers=True) is False


# ============================================================================
# PSAK67Rules - validation tests
# ============================================================================

class TestPSAK67Rules:
    def test_validate_ownership_interest_valid(self):
        oi = PSAK67OwnershipInterest(
            ownership_id=uuid4(),
            investee_id=uuid4(),
            investee_name="Test",
            relationship_type=PSAK67RelationshipType.SUBSIDIARY,
            ownership_percentage=Decimal("80"),
            voting_percentage=Decimal("80"),
            acquisition_date=datetime.now(UTC),
            control_assessment=PSAK67ControlAssessment.CONTROL,
        )
        result = PSAK67Rules.validate_ownership_interest(oi)
        assert result.is_compliant is True
        assert result.compliance_level == PSAK67ComplianceLevel.FULL

    def test_validate_ownership_interest_invalid_percentage(self):
        oi = PSAK67OwnershipInterest(
            ownership_id=uuid4(),
            investee_id=uuid4(),
            investee_name="Test",
            relationship_type=PSAK67RelationshipType.SUBSIDIARY,
            ownership_percentage=Decimal("120"),
            voting_percentage=Decimal("80"),
            acquisition_date=datetime.now(UTC),
            control_assessment=PSAK67ControlAssessment.CONTROL,
        )
        result = PSAK67Rules.validate_ownership_interest(oi)
        assert result.is_compliant is False
        assert "Persentase kepemilikan tidak valid" in result.errors

    def test_validate_ownership_interest_warning_for_subsidiary_no_control(self):
        oi = PSAK67OwnershipInterest(
            ownership_id=uuid4(),
            investee_id=uuid4(),
            investee_name="Test",
            relationship_type=PSAK67RelationshipType.SUBSIDIARY,
            ownership_percentage=Decimal("80"),
            voting_percentage=Decimal("80"),
            acquisition_date=datetime.now(UTC),
            control_assessment=PSAK67ControlAssessment.SIGNIFICANT_INFLUENCE,  # Not CONTROL
        )
        result = PSAK67Rules.validate_ownership_interest(oi)
        assert result.is_compliant is True
        assert "Entitas diklasifikasikan sebagai anak perusahaan tetapi kontrol tidak terpenuhi" in result.warnings

    def test_validate_nci_disclosure_valid(self):
        nci = PSAK67NonControllingInterest(
            nci_id=uuid4(),
            subsidiary_id=uuid4(),
            subsidiary_name="Test",
            nci_percentage=Decimal("20"),
            nci_measurement=PSAK67NCIChoice.PROPORTIONATE_SHARE,
            nci_amount=Decimal("1000000"),
        )
        result = PSAK67Rules.validate_nci_disclosure(nci)
        assert result.is_compliant is True
        assert result.compliance_level == PSAK67ComplianceLevel.FULL

    def test_validate_nci_disclosure_warning(self):
        nci = PSAK67NonControllingInterest(
            nci_id=uuid4(),
            subsidiary_id=uuid4(),
            subsidiary_name="Test",
            nci_percentage=Decimal("20"),
            nci_measurement=PSAK67NCIChoice.PROPORTIONATE_SHARE,
            nci_amount=Decimal("0"),  # zero amount with positive percentage
        )
        result = PSAK67Rules.validate_nci_disclosure(nci)
        assert result.is_compliant is True
        assert "Kepentingan non-pengendali positif dengan nilai nol atau negatif" in result.warnings

    def test_validate_structured_entity_warning(self):
        se = PSAK67StructuredEntity(
            entity_id=uuid4(),
            entity_name="SE",
            nature_of_relationship="Test",
            carrying_amount_assets=Decimal("5000000"),
            maximum_exposure_to_loss=Decimal("3000000"),  # less than assets
        )
        result = PSAK67Rules.validate_structured_entity(se)
        assert result.is_compliant is True
        assert "Eksposur maksimum kerugian kurang dari nilai tercatat aset" in result.warnings

    def test_validate_restriction_disclosure_error(self):
        restriction = PSAK67SignificantRestriction(
            restriction_id=uuid4(),
            investee_id=uuid4(),
            investee_name="Test",
            restriction_description="Desc",
            affected_assets="Assets",
            restricted_amount=Decimal("-100"),  # negative
        )
        result = PSAK67Rules.validate_restriction_disclosure(restriction)
        assert result.is_compliant is False
        assert "Nilai aset yang direstriksi tidak boleh negatif" in result.errors


# ============================================================================
# PSAK67Validator - full functional tests
# ============================================================================

class TestPSAK67Validator:
    @pytest.fixture
    def validator(self):
        return PSAK67Validator()

    @pytest.fixture
    def disclosure(self, validator):
        return validator.create_disclosure(
            entity_id=uuid4(),
            entity_name="PT Induk",
            reporting_date=datetime.now(UTC),
        )

    def test_create_disclosure(self, validator):
        entity_id = uuid4()
        d = validator.create_disclosure(entity_id, "PT Induk", datetime.now(UTC))
        assert d.entity_id == entity_id
        assert d.entity_name == "PT Induk"
        assert isinstance(d.disclosure_id, uuid4().__class__)
        assert d.ownership_interests == []
        assert d.non_controlling_interests == []
        assert d.structured_entities == []
        assert d.restrictions == []
        assert d.risks_from_structured_entities == []

    def test_create_ownership_interest(self, validator):
        investee_id = uuid4()
        oi = validator.create_ownership_interest(
            investee_id=investee_id,
            investee_name="PT Anak",
            relationship_type=PSAK67RelationshipType.SUBSIDIARY,
            ownership_percentage=Decimal("80"),
            voting_percentage=Decimal("80"),
            acquisition_date=datetime.now(UTC),
            has_contractual_control=True,
        )
        assert oi.investee_id == investee_id
        assert oi.investee_name == "PT Anak"
        assert oi.relationship_type == PSAK67RelationshipType.SUBSIDIARY
        assert oi.ownership_percentage == Decimal("80")
        assert oi.control_assessment == PSAK67ControlAssessment.CONTROL

    def test_create_non_controlling_interest(self, validator):
        subsidiary_id = uuid4()
        nci = validator.create_non_controlling_interest(
            subsidiary_id=subsidiary_id,
            subsidiary_name="PT Anak",
            nci_percentage=Decimal("20"),
            nci_measurement=PSAK67NCIChoice.PROPORTIONATE_SHARE,
            nci_amount=Decimal("1000000"),
            profit_allocated=Decimal("200000"),
            dividends_paid=Decimal("50000"),
        )
        assert nci.subsidiary_id == subsidiary_id
        assert nci.nci_percentage == Decimal("20")
        assert nci.nci_amount == Decimal("1000000")
        assert nci.profit_allocated_to_nci == Decimal("200000")
        assert nci.dividends_paid_to_nci == Decimal("50000")

    def test_create_structured_entity(self, validator):
        se = validator.create_structured_entity(
            entity_name="Dana XYZ",
            nature_of_relationship="Investasi variabel",
            carrying_amount_assets=Decimal("5000000"),
            carrying_amount_liabilities=Decimal("4500000"),
            maximum_exposure_to_loss=Decimal("500000"),
            funding_commitments=Decimal("100000"),
            liquidity_agreements="Komitmen",
        )
        assert se.entity_name == "Dana XYZ"
        assert se.carrying_amount_assets == Decimal("5000000")
        # Ensure max exposure is at least assets
        assert se.maximum_exposure_to_loss >= se.carrying_amount_assets

    def test_create_restriction(self, validator):
        investee_id = uuid4()
        r = validator.create_restriction(
            investee_id=investee_id,
            investee_name="PT Anak",
            restriction_description="Tidak boleh bagi dividen",
            affected_assets="Laba ditahan",
            restricted_amount=Decimal("200000000"),
        )
        assert r.investee_id == investee_id
        assert r.restricted_amount == Decimal("200000000")

    # --- ADD methods ---

    def test_add_ownership_interest(self, validator, disclosure):
        oi = validator.create_ownership_interest(
            investee_id=uuid4(),
            investee_name="PT Anak",
            relationship_type=PSAK67RelationshipType.SUBSIDIARY,
            ownership_percentage=Decimal("80"),
            voting_percentage=Decimal("80"),
            acquisition_date=datetime.now(UTC),
        )
        updated = validator.add_ownership_interest(disclosure, oi)
        assert len(updated.ownership_interests) == 1
        assert updated.ownership_interests[0] is oi
        # Check other fields are preserved
        assert updated.entity_id == disclosure.entity_id
        assert updated.entity_name == disclosure.entity_name
        assert updated.non_controlling_interests == disclosure.non_controlling_interests

    def test_add_nci(self, validator, disclosure):
        nci = validator.create_non_controlling_interest(
            subsidiary_id=uuid4(),
            subsidiary_name="PT Anak",
            nci_percentage=Decimal("20"),
            nci_measurement=PSAK67NCIChoice.PROPORTIONATE_SHARE,
            nci_amount=Decimal("1000000"),
        )
        updated = validator.add_nci(disclosure, nci)
        assert len(updated.non_controlling_interests) == 1
        assert updated.non_controlling_interests[0] is nci

    def test_add_structured_entity(self, validator, disclosure):
        se = validator.create_structured_entity(
            entity_name="Dana XYZ",
            nature_of_relationship="Test",
            carrying_amount_assets=Decimal("5000000"),
        )
        updated = validator.add_structured_entity(disclosure, se)
        assert len(updated.structured_entities) == 1
        assert updated.structured_entities[0] is se

    def test_add_restriction(self, validator, disclosure):
        r = validator.create_restriction(
            investee_id=uuid4(),
            investee_name="PT Anak",
            restriction_description="Test",
            affected_assets="All",
            restricted_amount=Decimal("100000"),
        )
        updated = validator.add_restriction(disclosure, r)
        assert len(updated.restrictions) == 1
        assert updated.restrictions[0] is r

    def test_add_risk(self, validator, disclosure):
        updated = validator.add_risk(disclosure, PSAK67RiskType.EXPOSURE_TO_LOSS, "High risk")
        assert len(updated.risks_from_structured_entities) == 1
        assert updated.risks_from_structured_entities[0] == (PSAK67RiskType.EXPOSURE_TO_LOSS, "High risk")

        # Add another risk
        updated2 = validator.add_risk(updated, PSAK67RiskType.FUNDING_COMMITMENT, "Funding commitment")
        assert len(updated2.risks_from_structured_entities) == 2

    # --- validate_disclosure ---

    def test_validate_disclosure_full_compliance(self, validator, disclosure):
        # Add a valid subsidiary
        oi = validator.create_ownership_interest(
            investee_id=uuid4(),
            investee_name="PT Anak",
            relationship_type=PSAK67RelationshipType.SUBSIDIARY,
            ownership_percentage=Decimal("80"),
            voting_percentage=Decimal("80"),
            acquisition_date=datetime.now(UTC),
            has_contractual_control=True,
        )
        disclosure = validator.add_ownership_interest(disclosure, oi)
        result = validator.validate_disclosure(disclosure)
        assert result.is_compliant is True
        assert result.compliance_level == PSAK67ComplianceLevel.FULL
        assert result.errors == []
        assert result.warnings == []

    def test_validate_disclosure_with_warnings(self, validator, disclosure):
        # Subsidiary without control (warning)
        oi = validator.create_ownership_interest(
            investee_id=uuid4(),
            investee_name="PT Anak",
            relationship_type=PSAK67RelationshipType.SUBSIDIARY,
            ownership_percentage=Decimal("80"),
            voting_percentage=Decimal("80"),
            acquisition_date=datetime.now(UTC),
            has_contractual_control=False,
        )
        disclosure = validator.add_ownership_interest(disclosure, oi)
        result = validator.validate_disclosure(disclosure)
        assert result.is_compliant is True
        assert result.compliance_level == PSAK67ComplianceLevel.SUBSTANTIAL
        assert len(result.warnings) > 0

    def test_validate_disclosure_with_errors(self, validator, disclosure):
        # Invalid percentage
        oi = validator.create_ownership_interest(
            investee_id=uuid4(),
            investee_name="PT Anak",
            relationship_type=PSAK67RelationshipType.SUBSIDIARY,
            ownership_percentage=Decimal("120"),
            voting_percentage=Decimal("80"),
            acquisition_date=datetime.now(UTC),
        )
        disclosure = validator.add_ownership_interest(disclosure, oi)
        result = validator.validate_disclosure(disclosure)
        assert result.is_compliant is False
        assert result.compliance_level == PSAK67ComplianceLevel.NON_COMPLIANT
        assert any("Persentase kepemilikan tidak valid" in e for e in result.errors)

    def test_get_requirements_summary(self, validator):
        summary = validator.get_requirements_summary()
        assert "objective" in summary
        assert "disclosures_for_subsidiaries" in summary
        assert "disclosures_for_joint_ventures_and_associates" in summary
        assert "disclosures_for_structured_entities" in summary
        assert "risks" in summary


# ============================================================================
# Singleton accessor test
# ============================================================================

def test_get_psak67_validator():
    v1 = get_psak67_validator()
    v2 = get_psak67_validator()
    assert v1 is v2
    assert isinstance(v1, PSAK67Validator)