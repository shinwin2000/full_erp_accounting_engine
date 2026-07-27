# tests/compliance/legal/test_compliance_scope_determiner.py
"""
Comprehensive tests for compliance/legal/compliance_scope_determiner.py
"""

import json
from datetime import datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from compliance.legal.compliance_scope_determiner import (
    ComplianceRequirement,
    ComplianceScope,
    ComplianceScopeDeterminer,
    EntityType,
    IndustrySector,
    JurisdictionError,
    ReportingFrequency,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_jurisdiction():
    jur = MagicMock()
    jur.code = "ID"
    jur.name = "Indonesia"
    jur.legal_system = "civil_law"
    return jur


@pytest.fixture
def mock_regulatory_body():
    body = MagicMock()
    body.code = "OJK"
    body.name = "Otoritas Jasa Keuangan"
    return body


@pytest.fixture
def mock_registry(mock_regulatory_body):
    registry = MagicMock()
    registry.get_body.return_value = mock_regulatory_body
    return registry


@pytest.fixture
def determiner(mock_registry, mock_jurisdiction):
    with patch("compliance.legal.compliance_scope_determiner.JurisdictionDefinition") as mock_jur_def:
        mock_jur_def_instance = MagicMock()
        mock_jur_def_instance.get_jurisdiction.return_value = mock_jurisdiction
        mock_jur_def_instance.get_all.return_value = [mock_jurisdiction]
        mock_jur_def.return_value = mock_jur_def_instance
        with patch("compliance.legal.compliance_scope_determiner.RegulatoryBodyRegistry") as mock_reg:
            mock_reg.return_value = mock_registry
            determiner = ComplianceScopeDeterminer()
            # Replace internal caches with controlled versions for testing
            determiner._jurisdiction_def = mock_jur_def_instance
            determiner._regulatory_registry = mock_registry
            yield determiner


# ============================================================================
# Tests for Enums
# ============================================================================

class TestEntityType:
    def test_members_exist(self):
        assert hasattr(EntityType, 'PUBLIC_LISTED')
        assert hasattr(EntityType, 'PRIVATE_LARGE')
        assert hasattr(EntityType, 'PRIVATE_MEDIUM')
        assert hasattr(EntityType, 'SME')
        assert hasattr(EntityType, 'STARTUP')
        assert hasattr(EntityType, 'NON_PROFIT')
        assert hasattr(EntityType, 'GOVERNMENT')

    def test_member_is_instance(self):
        assert isinstance(EntityType.PUBLIC_LISTED, EntityType)


class TestIndustrySector:
    def test_members_exist(self):
        assert hasattr(IndustrySector, 'BANKING')
        assert hasattr(IndustrySector, 'FINANCE')
        assert hasattr(IndustrySector, 'INSURANCE')
        assert hasattr(IndustrySector, 'CAPITAL_MARKET')
        assert hasattr(IndustrySector, 'MANUFACTURING')
        assert hasattr(IndustrySector, 'TRADE')
        assert hasattr(IndustrySector, 'SERVICES')
        assert hasattr(IndustrySector, 'CONSTRUCTION')
        assert hasattr(IndustrySector, 'PROPERTY')
        assert hasattr(IndustrySector, 'MINING')
        assert hasattr(IndustrySector, 'AGRICULTURE')
        assert hasattr(IndustrySector, 'TECHNOLOGY')
        assert hasattr(IndustrySector, 'HEALTHCARE')
        assert hasattr(IndustrySector, 'EDUCATION')
        assert hasattr(IndustrySector, 'TRANSPORTATION')
        assert hasattr(IndustrySector, 'ENERGY')
        assert hasattr(IndustrySector, 'TELECOMMUNICATIONS')
        assert hasattr(IndustrySector, 'MEDIA')
        assert hasattr(IndustrySector, 'OTHER')

    def test_member_is_instance(self):
        assert isinstance(IndustrySector.BANKING, IndustrySector)


class TestReportingFrequency:
    def test_members_exist(self):
        assert hasattr(ReportingFrequency, 'MONTHLY')
        assert hasattr(ReportingFrequency, 'QUARTERLY')
        assert hasattr(ReportingFrequency, 'SEMI_ANNUAL')
        assert hasattr(ReportingFrequency, 'ANNUAL')
        assert hasattr(ReportingFrequency, 'AD_HOC')

    def test_member_is_instance(self):
        assert isinstance(ReportingFrequency.MONTHLY, ReportingFrequency)


# ============================================================================
# Tests for ComplianceRequirement
# ============================================================================

class TestComplianceRequirement:
    def test_construction(self):
        req_id = uuid4()
        req = ComplianceRequirement(
            requirement_id=req_id,
            title="Test Requirement",
            regulatory_body="OJK",
            regulation="POJK No. 1/2020",
            frequency=ReportingFrequency.MONTHLY,
            due_day=15,
            due_month_offset=0,
            description="Test description",
            is_mandatory=True,
            applicable_to=[EntityType.PUBLIC_LISTED],
        )
        assert req.id == req_id
        assert req.title == "Test Requirement"
        assert req.regulatory_body == "OJK"
        assert req.frequency == ReportingFrequency.MONTHLY
        assert req.due_day == 15
        assert req.due_month_offset == 0
        assert req.description == "Test description"
        assert req.is_mandatory is True
        assert req.applicable_to == [EntityType.PUBLIC_LISTED]
        assert req._hash != ""

    def test_to_dict(self):
        req_id = uuid4()
        req = ComplianceRequirement(
            requirement_id=req_id,
            title="Test Requirement",
            regulatory_body="OJK",
            regulation="POJK No. 1/2020",
            frequency=ReportingFrequency.MONTHLY,
            due_day=15,
            due_month_offset=0,
            description="Test description",
            is_mandatory=True,
            applicable_to=[EntityType.PUBLIC_LISTED],
        )
        d = req.to_dict()
        assert d["id"] == str(req_id)
        assert d["title"] == "Test Requirement"
        assert d["regulatory_body"] == "OJK"
        assert d["regulation"] == "POJK No. 1/2020"
        assert d["frequency"] == "monthly"
        assert d["due_day"] == 15
        assert d["due_month_offset"] == 0
        assert d["description"] == "Test description"
        assert d["is_mandatory"] is True
        assert d["applicable_to"] == ["public_listed"]


# ============================================================================
# Tests for ComplianceScope
# ============================================================================

class TestComplianceScope:
    def test_construction(self, mock_jurisdiction):
        body = MagicMock()
        body.code = "OJK"
        body.name = "OJK"
        req = ComplianceRequirement(
            requirement_id=uuid4(),
            title="Test",
            regulatory_body="OJK",
            regulation="Reg",
            frequency=ReportingFrequency.MONTHLY,
            due_day=1,
            due_month_offset=0,
            description="desc",
        )
        scope = ComplianceScope(
            jurisdiction=mock_jurisdiction,
            entity_type=EntityType.PUBLIC_LISTED,
            industry=IndustrySector.BANKING,
            regulatory_bodies=[body],
            requirements=[req],
            accounting_standards=["PSAK"],
            tax_regime="CIT 22%",
            audit_requirements=["Annual audit"],
            additional_notes="Note",
        )
        assert scope.jurisdiction == mock_jurisdiction
        assert scope.entity_type == EntityType.PUBLIC_LISTED
        assert scope.industry == IndustrySector.BANKING
        assert scope.regulatory_bodies == [body]
        assert scope.requirements == [req]
        assert scope.accounting_standards == ["PSAK"]
        assert scope.tax_regime == "CIT 22%"
        assert scope.audit_requirements == ["Annual audit"]
        assert scope.additional_notes == "Note"
        assert scope._hash != ""

    def test_to_dict(self, mock_jurisdiction):
        body = MagicMock()
        body.code = "OJK"
        body.name = "OJK"
        req = ComplianceRequirement(
            requirement_id=uuid4(),
            title="Test",
            regulatory_body="OJK",
            regulation="Reg",
            frequency=ReportingFrequency.MONTHLY,
            due_day=1,
            due_month_offset=0,
            description="desc",
        )
        scope = ComplianceScope(
            jurisdiction=mock_jurisdiction,
            entity_type=EntityType.PUBLIC_LISTED,
            industry=IndustrySector.BANKING,
            regulatory_bodies=[body],
            requirements=[req],
            accounting_standards=["PSAK"],
            tax_regime="CIT 22%",
            audit_requirements=["Annual audit"],
            additional_notes="Note",
        )
        d = scope.to_dict()
        assert d["jurisdiction"]["code"] == "ID"
        assert d["jurisdiction"]["name"] == "Indonesia"
        assert d["entity_type"] == "public_listed"
        assert d["industry"] == "banking"
        assert d["regulatory_bodies"][0]["code"] == "OJK"
        assert d["requirements"][0]["title"] == "Test"
        assert d["accounting_standards"] == ["PSAK"]
        assert d["tax_regime"] == "CIT 22%"
        assert d["audit_requirements"] == ["Annual audit"]
        assert d["additional_notes"] == "Note"
        assert "determined_at" in d
        assert "hash" in d


# ============================================================================
# Tests for ComplianceScopeDeterminer
# ============================================================================

class TestComplianceScopeDeterminer:
    def test_init_populates_default_requirements(self, determiner):
        # Should have default requirements in cache
        assert len(determiner._requirements_cache) > 0
        # Check that at least OJK, DJP, BI, MAS, IRAS etc are present
        assert "OJK" in determiner._requirements_cache
        assert "DJP" in determiner._requirements_cache
        assert "BI" in determiner._requirements_cache

    def test_add_requirement(self, determiner):
        req = ComplianceRequirement(
            requirement_id=uuid4(),
            title="New Requirement",
            regulatory_body="Custom",
            regulation="Custom Reg",
            frequency=ReportingFrequency.ANNUAL,
            due_day=1,
            due_month_offset=0,
            description="desc",
        )
        determiner._add_requirement(req)
        assert "Custom" in determiner._requirements_cache
        assert len(determiner._requirements_cache["Custom"]) == 1
        assert determiner._requirements_cache["Custom"][0].title == "New Requirement"

    def test_determine_scope_success(self, determiner, mock_jurisdiction):
        scope = determiner.determine_scope(
            jurisdiction_code="ID",
            entity_type=EntityType.PUBLIC_LISTED,
            industry=IndustrySector.MANUFACTURING,
            is_consolidated_group=True,
        )
        assert isinstance(scope, ComplianceScope)
        assert scope.jurisdiction == mock_jurisdiction
        assert scope.entity_type == EntityType.PUBLIC_LISTED
        assert scope.industry == IndustrySector.MANUFACTURING
        # Regulatory bodies: DJP always, OJK? For manufacturing, OJK only if banking/finance/insurance/capital_market, so not included.
        # So only DJP should be present.
        # Check that DJP is in the list
        djp_present = any(b.code == "DJP" for b in scope.regulatory_bodies)
        assert djp_present
        ojk_present = any(b.code == "OJK" for b in scope.regulatory_bodies)
        assert ojk_present is False  # because manufacturing not financial
        # Requirements: should include DJP and OJK? OJK not applicable because not financial
        # So only DJP requirements
        djp_reqs = [r for r in scope.requirements if r.regulatory_body == "DJP"]
        assert len(djp_reqs) > 0
        ojk_reqs = [r for r in scope.requirements if r.regulatory_body == "OJK"]
        # OJK requirements should not be included because entity type PUBLIC_LISTED but industry not financial? Actually the _determine_applicable_requirements checks regulatory body based on jurisdiction, not industry. It uses a simple condition: if jurisdiction_code == "ID" and regulatory_body in ["OJK", "DJP", "BI"], then include if applicable_to matches.
        # So OJK requirements will be included if applicable_to includes PUBLIC_LISTED. The default OJK LKPBU applies to PUBLIC_LISTED, so it should be included regardless of industry. So OJK requirements will be present.
        # Let's check that at least one OJK requirement is present because it's applicable to PUBLIC_LISTED.
        ojk_reqs = [r for r in scope.requirements if r.regulatory_body == "OJK"]
        assert len(ojk_reqs) > 0
        # Check accounting standards: should be PSAK (IFRS converged) for public listed in ID
        assert "PSAK (IFRS converged)" in scope.accounting_standards
        # Tax regime: ID + PUBLIC_LISTED -> General (CIT 22%)
        assert scope.tax_regime == "General (CIT 22%)"
        # Audit requirements: PUBLIC_LISTED should have annual audit and quarterly review
        assert "Annual audit by registered public accountant (KAP)" in scope.audit_requirements
        # Additional notes should include consolidated note
        assert "Consolidated group reporting" in scope.additional_notes

    def test_determine_scope_financial_industry(self, determiner, mock_jurisdiction):
        scope = determiner.determine_scope(
            jurisdiction_code="ID",
            entity_type=EntityType.PUBLIC_LISTED,
            industry=IndustrySector.BANKING,
            is_consolidated_group=False,
        )
        # OJK and BI should be present
        ojk_present = any(b.code == "OJK" for b in scope.regulatory_bodies)
        bi_present = any(b.code == "BI" for b in scope.regulatory_bodies)
        assert ojk_present is True
        assert bi_present is True
        # BI requirement should be present (Laporan Transaksi Valuta Asing)
        bi_reqs = [r for r in scope.requirements if r.regulatory_body == "BI"]
        assert len(bi_reqs) > 0
        # Additional notes should not include consolidated note
        assert "Consolidated group reporting" not in scope.additional_notes
        # Should include banking note
        assert "Banking sector has additional capital adequacy" in scope.additional_notes

    def test_determine_scope_sme(self, determiner, mock_jurisdiction):
        scope = determiner.determine_scope(
            jurisdiction_code="ID",
            entity_type=EntityType.SME,
            industry=IndustrySector.MANUFACTURING,
            is_consolidated_group=False,
        )
        # SME should have SAK ETAP in accounting standards
        assert "SAK ETAP" in scope.accounting_standards
        # Tax regime for SME in ID: "SME facility (CIT 11% up to 4.8B)"
        assert scope.tax_regime == "SME facility (CIT 11% up to 4.8B)"
        # Audit requirements: not mandatory
        assert "Audit not mandatory" in scope.audit_requirements

    def test_determine_scope_startup(self, determiner, mock_jurisdiction):
        scope = determiner.determine_scope(
            jurisdiction_code="ID",
            entity_type=EntityType.STARTUP,
            industry=IndustrySector.TECHNOLOGY,
            is_consolidated_group=False,
        )
        # Accounting standards: SAK UMKM for startup
        assert "SAK UMKM" in scope.accounting_standards
        # Tax regime: "Startup incentives (tax holiday)"
        assert "Startup incentives" in scope.tax_regime

    def test_determine_scope_singapore(self, determiner, mock_jurisdiction):
        # Override jurisdiction for SG
        sg_jur = MagicMock()
        sg_jur.code = "SG"
        sg_jur.name = "Singapore"
        sg_jur.legal_system = "common_law"
        determiner._jurisdiction_def.get_jurisdiction.return_value = sg_jur

        scope = determiner.determine_scope(
            jurisdiction_code="SG",
            entity_type=EntityType.PUBLIC_LISTED,
            industry=IndustrySector.FINANCE,
            is_consolidated_group=False,
        )
        # Regulatory bodies: IRAS and MAS
        iras_present = any(b.code == "IRAS" for b in scope.regulatory_bodies)
        mas_present = any(b.code == "MAS" for b in scope.regulatory_bodies)
        assert iras_present is True
        assert mas_present is True
        # Accounting standards: SFRS for public listed
        assert "SFRS (Singapore FRS)" in scope.accounting_standards
        # Tax regime: CIT 17% with partial exemption
        assert scope.tax_regime == "CIT 17% with partial exemption"

    def test_determine_scope_us(self, determiner, mock_jurisdiction):
        us_jur = MagicMock()
        us_jur.code = "US"
        us_jur.name = "United States"
        us_jur.legal_system = "common_law"
        determiner._jurisdiction_def.get_jurisdiction.return_value = us_jur

        scope = determiner.determine_scope(
            jurisdiction_code="US",
            entity_type=EntityType.PRIVATE_LARGE,
            industry=IndustrySector.MANUFACTURING,
            is_consolidated_group=False,
        )
        # Regulatory bodies: IRS, and SEC? only if capital_market, not manufacturing, so SEC not included
        irs_present = any(b.code == "IRS" for b in scope.regulatory_bodies)
        sec_present = any(b.code == "SEC" for b in scope.regulatory_bodies)
        assert irs_present is True
        assert sec_present is False
        # Accounting standards: US GAAP
        assert "US GAAP" in scope.accounting_standards
        # Tax regime: Federal CIT 21% + state taxes
        assert scope.tax_regime == "Federal CIT 21% + state taxes"

    def test_determine_scope_invalid_jurisdiction_raises(self, determiner):
        determiner._jurisdiction_def.get_jurisdiction.side_effect = ValueError("Not found")
        with pytest.raises(JurisdictionError, match="Jurisdiction XX not supported"):
            determiner.determine_scope(
                jurisdiction_code="XX",
                entity_type=EntityType.PUBLIC_LISTED,
                industry=IndustrySector.MANUFACTURING,
            )

    def test_get_available_jurisdictions(self, determiner):
        jurisdictions = determiner.get_available_jurisdictions()
        assert jurisdictions == ["ID"]  # our mock only has ID

    def test_get_requirements_summary(self, determiner):
        summary = determiner.get_requirements_summary()
        assert "total_requirements" in summary
        assert summary["total_requirements"] > 0
        assert "by_regulator" in summary
        # Check that some regulators are present
        assert "OJK" in summary["by_regulator"]
        assert "DJP" in summary["by_regulator"]

    def test_determine_applicable_requirements_for_id_public_listed(self, determiner):
        # Test the private method directly
        reqs = determiner._determine_applicable_requirements(
            jurisdiction_code="ID",
            entity_type=EntityType.PUBLIC_LISTED,
            industry=IndustrySector.MANUFACTURING,
        )
        # Should include OJK and DJP requirements applicable to PUBLIC_LISTED
        ojk_reqs = [r for r in reqs if r.regulatory_body == "OJK"]
        djp_reqs = [r for r in reqs if r.regulatory_body == "DJP"]
        assert len(ojk_reqs) > 0
        assert len(djp_reqs) > 0
        # BI should not be included because industry not banking/finance? Actually _determine_applicable_requirements doesn't check industry for BI? It checks jurisdiction_code == "ID" and regulatory_body in ["OJK", "DJP", "BI"], so BI requirements will be included if applicable_to includes PUBLIC_LISTED. The default BI requirement applies to BANKING and FINANCE only, so it won't be included.
        bi_reqs = [r for r in reqs if r.regulatory_body == "BI"]
        assert len(bi_reqs) == 0

    def test_determine_applicable_requirements_for_id_banking(self, determiner):
        reqs = determiner._determine_applicable_requirements(
            jurisdiction_code="ID",
            entity_type=EntityType.PUBLIC_LISTED,
            industry=IndustrySector.BANKING,
        )
        bi_reqs = [r for r in reqs if r.regulatory_body == "BI"]
        assert len(bi_reqs) > 0

    def test_determine_applicable_requirements_for_sg(self, determiner):
        reqs = determiner._determine_applicable_requirements(
            jurisdiction_code="SG",
            entity_type=EntityType.PUBLIC_LISTED,
            industry=IndustrySector.FINANCE,
        )
        # Should include MAS and IRAS requirements
        mas_reqs = [r for r in reqs if r.regulatory_body == "MAS"]
        iras_reqs = [r for r in reqs if r.regulatory_body == "IRAS"]
        assert len(mas_reqs) > 0
        assert len(iras_reqs) > 0

    def test_determine_accounting_standards_id_public(self, determiner):
        standards = determiner._determine_accounting_standards("ID", EntityType.PUBLIC_LISTED)
        assert "PSAK (IFRS converged)" in standards

    def test_determine_accounting_standards_id_sme(self, determiner):
        standards = determiner._determine_accounting_standards("ID", EntityType.SME)
        assert "SAK ETAP" in standards

    def test_determine_accounting_standards_id_startup(self, determiner):
        standards = determiner._determine_accounting_standards("ID", EntityType.STARTUP)
        assert "SAK UMKM" in standards

    def test_determine_accounting_standards_sg(self, determiner):
        standards = determiner._determine_accounting_standards("SG", EntityType.PUBLIC_LISTED)
        assert "SFRS (Singapore FRS)" in standards

    def test_determine_accounting_standards_us(self, determiner):
        standards = determiner._determine_accounting_standards("US", EntityType.PUBLIC_LISTED)
        assert "US GAAP" in standards

    def test_determine_tax_regime_id_public(self, determiner):
        regime = determiner._determine_tax_regime("ID", EntityType.PUBLIC_LISTED)
        assert regime == "General (CIT 22%)"

    def test_determine_tax_regime_id_sme(self, determiner):
        regime = determiner._determine_tax_regime("ID", EntityType.SME)
        assert regime == "SME facility (CIT 11% up to 4.8B)"

    def test_determine_tax_regime_id_startup(self, determiner):
        regime = determiner._determine_tax_regime("ID", EntityType.STARTUP)
        assert regime == "Startup incentives (tax holiday) - subject to qualification"

    def test_determine_tax_regime_sg_startup(self, determiner):
        regime = determiner._determine_tax_regime("SG", EntityType.STARTUP)
        assert regime == "Startup Tax Exemption (SUTE) for first 3 years"

    def test_determine_tax_regime_unknown_jurisdiction(self, determiner):
        regime = determiner._determine_tax_regime("XX", EntityType.PUBLIC_LISTED)
        assert regime == "Local tax regime"

    def test_determine_audit_requirements_public(self, determiner):
        reqs = determiner._determine_audit_requirements("ID", EntityType.PUBLIC_LISTED)
        assert "Annual audit by registered public accountant (KAP)" in reqs
        assert "Quarterly review for listed entities" in reqs

    def test_determine_audit_requirements_private_large(self, determiner):
        reqs = determiner._determine_audit_requirements("ID", EntityType.PRIVATE_LARGE)
        assert "Annual audit if exceeding certain asset/revenue thresholds" in reqs

    def test_determine_audit_requirements_sme(self, determiner):
        reqs = determiner._determine_audit_requirements("ID", EntityType.SME)
        assert "Audit not mandatory" in reqs

    def test_generate_notes_consolidated(self, determiner):
        notes = determiner._generate_notes("ID", EntityType.PUBLIC_LISTED, IndustrySector.MANUFACTURING, True)
        assert "Consolidated group reporting" in notes

    def test_generate_notes_banking(self, determiner):
        notes = determiner._generate_notes("ID", EntityType.PUBLIC_LISTED, IndustrySector.BANKING, False)
        assert "Banking sector has additional capital adequacy" in notes

    def test_generate_notes_id_public(self, determiner):
        notes = determiner._generate_notes("ID", EntityType.PUBLIC_LISTED, IndustrySector.MANUFACTURING, False)
        assert "Must comply with OJK regulations for public companies (POJK)" in notes

    def test_determine_regulatory_bodies_id_manufacturing(self, determiner):
        bodies = determiner._determine_regulatory_bodies("ID", IndustrySector.MANUFACTURING)
        # DJP always, OJK? No, only financial sectors, so only DJP.
        codes = [b.code for b in bodies]
        assert "DJP" in codes
        assert "OJK" not in codes
        assert "BI" not in codes

    def test_determine_regulatory_bodies_id_banking(self, determiner):
        bodies = determiner._determine_regulatory_bodies("ID", IndustrySector.BANKING)
        codes = [b.code for b in bodies]
        assert "DJP" in codes
        assert "OJK" in codes
        assert "BI" in codes

    def test_determine_regulatory_bodies_sg_finance(self, determiner):
        bodies = determiner._determine_regulatory_bodies("SG", IndustrySector.FINANCE)
        codes = [b.code for b in bodies]
        assert "IRAS" in codes
        assert "MAS" in codes

    def test_determine_regulatory_bodies_us_capital_market(self, determiner):
        bodies = determiner._determine_regulatory_bodies("US", IndustrySector.CAPITAL_MARKET)
        codes = [b.code for b in bodies]
        assert "IRS" in codes
        assert "SEC" in codes

    def test_determine_regulatory_bodies_unknown(self, determiner):
        bodies = determiner._determine_regulatory_bodies("XX", IndustrySector.OTHER)
        # Should return empty list because no mapping for XX
        assert bodies == []