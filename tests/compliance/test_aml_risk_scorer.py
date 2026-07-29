# test_aml_risk_scorer.py
# Comprehensive tests for compliance/aml_risk_scorer.py
# Covers all classes, methods, edge cases, exceptions, and domain logic.

from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
import requests

from compliance.aml_risk_scorer import (
    AMLError,
    AMLRiskScorer,
    CustomerProfile,
    CustomerRiskCategory,
    EDDStatus,
    PPATKAPIClient,
    RiskLevel,
    SanctionListEntry,
    SanctionListManager,
    SanctionListUnavailableError,
    STRSubmissionError,
    SuspiciousTransactionReport,
    TransactionRecord,
    TransactionType,
)

# Import the custom exception (may be defined in a separate module)
try:
    from compliance.compliance_exceptions import SuspiciousTransactionReported
except ImportError:
    # Create a dummy for testing if the module is not available
    class SuspiciousTransactionReported(Exception):
        def __init__(self, message, report_id=None, destination=None):
            self.message = message
            self.report_id = report_id
            self.destination = destination
            super().__init__(message)


# -------------------- Fixtures --------------------
@pytest.fixture
def customer_profile():
    return CustomerProfile(
        customer_id=uuid4(),
        legal_name="John Doe",
        country_code="ID",
        registration_date=date.today() - timedelta(days=365*2),  # 2 years old
        is_pep=False,
        pep_source=None,
        annual_income_estimation=Decimal("500000000"),
        occupation="Engineer",
        previous_str_count=0,
        edd_status=EDDStatus.NOT_REQUIRED,
        risk_score_cached=0,
        risk_level_cached=RiskLevel.LOW,
        last_assessment_date=None,
    )


@pytest.fixture
def transaction_record(customer_profile):
    return TransactionRecord(
        transaction_id=uuid4(),
        customer_id=customer_profile.customer_id,
        amount=Decimal("100000000"),  # 100 million
        currency="IDR",
        transaction_type=TransactionType.DEPOSIT,
        timestamp=datetime.utcnow(),
        counterparty_name="Counterparty X",
        counterparty_country="US",
        payment_method="bank_transfer",
        source_ip="192.168.1.1",
        device_fingerprint="fp123",
    )


@pytest.fixture
def sanction_entry():
    return SanctionListEntry(
        name="OSAMA BIN LADEN",
        list_name="UNSC 1267",
        reason="Terrorism",
        listed_date=date(2001, 9, 11),
        aliases=["Usama bin Laden"],
        country="SA",
        source_url="https://example.com",
    )


@pytest.fixture
def sanction_manager():
    return SanctionListManager(enable_remote_fetch=False)


@pytest.fixture
def ppatk_client():
    return PPATKAPIClient(base_url="https://test.ppatk.go.id", api_key="test_key")


@pytest.fixture
def risk_scorer(sanction_manager, ppatk_client):
    scorer = AMLRiskScorer(sanction_manager=sanction_manager, ppatk_client=ppatk_client)
    # Add some default high risk countries
    scorer._high_risk_countries = {"AF", "IQ", "SY", "IR", "KP", "RU"}
    return scorer


@pytest.fixture
def registered_customer(risk_scorer, customer_profile):
    risk_scorer.register_customer(customer_profile)
    return customer_profile


# -------------------- Tests for Enums --------------------
class TestEnums:
    def test_risk_level(self):
        assert RiskLevel.LOW.value == "low"
        assert RiskLevel.MEDIUM.value == "medium"
        assert RiskLevel.HIGH.value == "high"
        assert RiskLevel.CRITICAL.value == "critical"

    def test_transaction_type(self):
        assert TransactionType.DEPOSIT.value == "deposit"
        assert TransactionType.WITHDRAWAL.value == "withdrawal"
        assert TransactionType.TRANSFER.value == "transfer"
        assert TransactionType.PAYMENT.value == "payment"
        assert TransactionType.TRADE.value == "trade"
        assert TransactionType.CROSS_BORDER.value == "cross_border"

    def test_customer_risk_category(self):
        assert CustomerRiskCategory.STANDARD.value == "standard"
        assert CustomerRiskCategory.PEP.value == "pep"
        assert CustomerRiskCategory.SANCTION_HIT.value == "sanction_hit"
        assert CustomerRiskCategory.HIGH_RISK_JURISDICTION.value == "high_risk_jurisdiction"
        assert CustomerRiskCategory.NEW_CUSTOMER.value == "new_customer"
        assert CustomerRiskCategory.FREQUENT_STR.value == "frequent_str"

    def test_edd_status(self):
        assert EDDStatus.NOT_REQUIRED.value == "not_required"
        assert EDDStatus.REQUIRED.value == "required"
        assert EDDStatus.IN_PROGRESS.value == "in_progress"
        assert EDDStatus.COMPLETED.value == "completed"


# -------------------- Tests for Data Classes --------------------
class TestCustomerProfile:
    def test_age_in_years(self, customer_profile):
        # Fixed date for testing
        ref_date = date(2025, 1, 1)
        # registration was 2 years ago
        with patch("compliance.aml_risk_scorer.date") as mock_date:
            mock_date.today.return_value = ref_date
            age = customer_profile.age_in_years()
            assert age == 2  # since 2 years from registration

    def test_age_in_years_with_ref(self, customer_profile):
        ref_date = date(2025, 1, 1)
        assert customer_profile.age_in_years(ref_date) == 2


class TestSanctionListEntry:
    def test_construction(self, sanction_entry):
        assert sanction_entry.name == "OSAMA BIN LADEN"
        assert sanction_entry.list_name == "UNSC 1267"
        assert len(sanction_entry.aliases) == 1


class TestTransactionRecord:
    def test_construction(self, transaction_record):
        assert transaction_record.amount == Decimal("100000000")
        assert transaction_record.transaction_type == TransactionType.DEPOSIT


class TestSuspiciousTransactionReport:
    def test_construction(self):
        report = SuspiciousTransactionReport(
            report_id=uuid4(),
            transaction_id=uuid4(),
            reporter_id=uuid4(),
            amount=Decimal("1000000000"),
            currency="IDR",
            date=datetime.utcnow(),
            risk_score=85,
            risk_level=RiskLevel.CRITICAL,
            reasons=["High amount", "Sanction hit"],
        )
        assert report.submitted_at is None
        assert report.hash_chain_link is None

    def test_submit_success(self):
        report = SuspiciousTransactionReport(
            report_id=uuid4(),
            transaction_id=uuid4(),
            reporter_id=uuid4(),
            amount=Decimal("1000000000"),
            currency="IDR",
            date=datetime.utcnow(),
            risk_score=85,
            risk_level=RiskLevel.CRITICAL,
            reasons=["High amount"],
        )
        mock_client = MagicMock(spec=PPATKAPIClient)
        mock_response = MagicMock()
        mock_response.reference = "PPATK-REF123"
        mock_client.submit_str.return_value = mock_response

        result = report.submit(mock_client)
        assert result is True
        assert report.submitted_at is not None
        assert report.submission_reference == "PPATK-REF123"
        assert report.hash_chain_link is not None
        mock_client.submit_str.assert_called_once_with(report)

    def test_submit_already_submitted(self):
        report = SuspiciousTransactionReport(
            report_id=uuid4(),
            transaction_id=uuid4(),
            reporter_id=uuid4(),
            amount=Decimal("1000000000"),
            currency="IDR",
            date=datetime.utcnow(),
            risk_score=85,
            risk_level=RiskLevel.CRITICAL,
            reasons=["High amount"],
            submitted_at=datetime.utcnow(),
        )
        mock_client = MagicMock()
        result = report.submit(mock_client)
        assert result is True
        mock_client.submit_str.assert_not_called()

    def test_submit_failure(self):
        report = SuspiciousTransactionReport(
            report_id=uuid4(),
            transaction_id=uuid4(),
            reporter_id=uuid4(),
            amount=Decimal("1000000000"),
            currency="IDR",
            date=datetime.utcnow(),
            risk_score=85,
            risk_level=RiskLevel.CRITICAL,
            reasons=["High amount"],
        )
        mock_client = MagicMock()
        mock_client.submit_str.side_effect = Exception("Network error")
        result = report.submit(mock_client)
        assert result is False
        assert report.submitted_at is None


# -------------------- Tests for SanctionListManager --------------------
class TestSanctionListManager:
    def test_construction(self):
        manager = SanctionListManager(enable_remote_fetch=False)
        assert manager._entries is not None
        assert manager._last_fetch is None

    def test_construction_with_remote(self):
        with patch.object(SanctionListManager, "_fetch_remote_lists") as mock_fetch:
            manager = SanctionListManager(enable_remote_fetch=True)
            mock_fetch.assert_called_once()

    def test_create_session(self, sanction_manager):
        session = sanction_manager._create_session()
        assert isinstance(session, requests.Session)
        assert session.headers["User-Agent"] == "ERP-Accounting-Engine/1.0"

    def test_load_default_entries(self, sanction_manager):
        # Called in __init__
        assert len(sanction_manager._entries) > 0
        # Check known entries exist
        normalized = sanction_manager._normalize_name("OSAMA BIN LADEN")
        assert normalized in sanction_manager._entries
        assert sanction_manager._entries[normalized].name == "OSAMA BIN LADEN"

    def test_fetch_remote_lists(self, sanction_manager):
        with patch("compliance.aml_risk_scorer.logger") as mock_logger:
            sanction_manager._fetch_remote_lists()
            assert sanction_manager._last_fetch is not None
            mock_logger.info.assert_called_once_with("Sanction list remote fetch simulated (no network call)")

    def test_normalize_name(self, sanction_manager):
        assert sanction_manager._normalize_name("  hello  ") == "HELLO"
        assert sanction_manager._normalize_name("world") == "WORLD"

    def test_check_name_exact_match(self, sanction_manager):
        entry = sanction_manager.check_name("OSAMA BIN LADEN")
        assert entry is not None
        assert entry.name == "OSAMA BIN LADEN"

    def test_check_name_alias_match(self, sanction_manager):
        entry = sanction_manager.check_name("Usama bin Laden")
        assert entry is not None
        assert entry.name == "OSAMA BIN LADEN"

    def test_check_name_partial_match(self, sanction_manager):
        entry = sanction_manager.check_name("BIN LADEN")
        assert entry is not None
        assert entry.name == "OSAMA BIN LADEN"

    def test_check_name_no_match(self, sanction_manager):
        entry = sanction_manager.check_name("INVALID NAME")
        assert entry is None

    def test_add_entry(self, sanction_manager):
        new_entry = SanctionListEntry(
            name="NEW TERRORIST",
            list_name="UNSC",
            reason="Terrorism",
            listed_date=date.today(),
            aliases=["NT"],
        )
        sanction_manager.add_entry(new_entry)
        assert sanction_manager.check_name("NEW TERRORIST") == new_entry
        assert sanction_manager.check_name("NT") == new_entry

    def test_refresh(self, sanction_manager):
        with patch.object(sanction_manager, "_fetch_remote_lists") as mock_fetch:
            sanction_manager.refresh()
            mock_fetch.assert_called_once()


# -------------------- Tests for PPATKAPIClient --------------------
class TestPPATKAPIClient:
    def test_construction(self):
        client = PPATKAPIClient(base_url="https://test.api", api_key="key123")
        assert client.base_url == "https://test.api"
        assert client.api_key == "key123"

    def test_create_session(self, ppatk_client):
        session = ppatk_client._create_session()
        assert isinstance(session, requests.Session)
        assert session.headers["Authorization"] == "Bearer test_key"
        assert session.headers["Content-Type"] == "application/json"

    def test_submit_str(self, ppatk_client):
        report = SuspiciousTransactionReport(
            report_id=uuid4(),
            transaction_id=uuid4(),
            reporter_id=uuid4(),
            amount=Decimal("1000000000"),
            currency="IDR",
            date=datetime.utcnow(),
            risk_score=85,
            risk_level=RiskLevel.CRITICAL,
            reasons=["High amount"],
        )
        response = ppatk_client.submit_str(report)
        assert response.reference.startswith("PPATK-")
        assert len(response.reference) == 8 + 6  # "PPATK-" + 8 hex chars


# -------------------- Tests for AMLRiskScorer --------------------
class TestAMLRiskScorer:
    def test_construction(self):
        scorer = AMLRiskScorer()
        assert isinstance(scorer._sanction_manager, SanctionListManager)
        assert isinstance(scorer._ppatk_client, PPATKAPIClient)
        assert scorer._customer_profiles == {}
        assert scorer._transaction_history == {}
        assert scorer._str_reports == []

    def test_register_customer(self, risk_scorer, customer_profile):
        risk_scorer.register_customer(customer_profile)
        assert risk_scorer._customer_profiles[customer_profile.customer_id] == customer_profile

    def test_update_customer_profile(self, risk_scorer, registered_customer):
        risk_scorer.update_customer_profile(registered_customer.customer_id, legal_name="New Name")
        updated = risk_scorer._customer_profiles[registered_customer.customer_id]
        assert updated.legal_name == "New Name"
        assert updated.last_assessment_date is None  # invalidated

    def test_update_customer_profile_not_found(self, risk_scorer):
        with pytest.raises(AMLError, match="Customer .* not found"):
            risk_scorer.update_customer_profile(uuid4())

    # ---- calculate_risk_score ----
    def test_calculate_risk_score_basic(self, risk_scorer, registered_customer, transaction_record):
        score = risk_scorer.calculate_risk_score(registered_customer, transaction_record)
        # Amount 100 million => 15 points
        # Country ID not high risk => 0
        # Tenure 2 years => 10 points
        # Payment method bank_transfer => 0
        # Not PEP => 0
        # Previous STR = 0 => 0
        # Transaction type DEPOSIT => 0
        # Velocity check: no history => 0
        # Round amount? 100,000,000 is round => 5
        # Total = 15+10+5 = 30 => MEDIUM (30-59)
        assert score == 30

    def test_calculate_risk_score_with_sanction(self, risk_scorer, registered_customer, transaction_record):
        registered_customer.legal_name = "OSAMA BIN LADEN"
        score = risk_scorer.calculate_risk_score(registered_customer, transaction_record)
        assert score == 100  # Sanction override

    def test_calculate_risk_score_high_amount(self, risk_scorer, registered_customer, transaction_record):
        transaction_record.amount = Decimal("2000000000")  # 2 billion
        score = risk_scorer.calculate_risk_score(registered_customer, transaction_record)
        # Amount >= 1B => 40 points
        # Tenure 2 years => 10
        # Round amount => 5
        # Total = 55 => HIGH
        assert score == 55

    def test_calculate_risk_score_pep(self, risk_scorer, registered_customer, transaction_record):
        registered_customer.is_pep = True
        score = risk_scorer.calculate_risk_score(registered_customer, transaction_record)
        # 30 (PEP) + 15 (amount) + 10 (tenure) + 5 (round) = 60 => HIGH (>=60)
        assert score == 60

    def test_calculate_risk_score_high_risk_country(self, risk_scorer, registered_customer, transaction_record):
        transaction_record.counterparty_country = "AF"  # high risk
        score = risk_scorer.calculate_risk_score(registered_customer, transaction_record)
        # 25 (counterparty country) + 15 (amount) + 10 (tenure) + 5 (round) = 55
        assert score == 55

    def test_calculate_risk_score_customer_in_high_risk(self, risk_scorer, registered_customer, transaction_record):
        registered_customer.country_code = "IR"
        score = risk_scorer.calculate_risk_score(registered_customer, transaction_record)
        # 15 (customer country) + 15 (amount) + 10 (tenure) + 5 (round) = 45
        assert score == 45

    def test_calculate_risk_score_cash_payment(self, risk_scorer, registered_customer, transaction_record):
        transaction_record.payment_method = "cash"
        score = risk_scorer.calculate_risk_score(registered_customer, transaction_record)
        # 15 (cash) + 15 (amount) + 10 (tenure) + 5 (round) = 45
        assert score == 45

    def test_calculate_risk_score_crypto(self, risk_scorer, registered_customer, transaction_record):
        transaction_record.payment_method = "cryptocurrency"
        score = risk_scorer.calculate_risk_score(registered_customer, transaction_record)
        # 30 (crypto) + 15 (amount) + 10 (tenure) + 5 (round) = 60
        assert score == 60

    def test_calculate_risk_score_new_customer(self, risk_scorer, registered_customer, transaction_record):
        registered_customer.registration_date = date.today() - timedelta(days=100)
        score = risk_scorer.calculate_risk_score(registered_customer, transaction_record)
        # New customer => 20 instead of 10
        # 15 (amount) + 20 (tenure) + 5 (round) = 40
        assert score == 40

    def test_calculate_risk_score_previous_str(self, risk_scorer, registered_customer, transaction_record):
        registered_customer.previous_str_count = 3
        score = risk_scorer.calculate_risk_score(registered_customer, transaction_record)
        # 30 (max from previous STR) + 15 (amount) + 10 (tenure) + 5 (round) = 60
        assert score == 60

    def test_calculate_risk_score_cross_border(self, risk_scorer, registered_customer, transaction_record):
        transaction_record.transaction_type = TransactionType.CROSS_BORDER
        score = risk_scorer.calculate_risk_score(registered_customer, transaction_record)
        # 20 (cross-border) + 15 (amount) + 10 (tenure) + 5 (round) = 50
        assert score == 50

    def test_calculate_risk_score_trade_large(self, risk_scorer, registered_customer, transaction_record):
        transaction_record.transaction_type = TransactionType.TRADE
        transaction_record.amount = Decimal("600000000")
        score = risk_scorer.calculate_risk_score(registered_customer, transaction_record)
        # 10 (trade > 500M) + 30 (amount 500M-1B) + 10 (tenure) + 5 (round) = 55
        assert score == 55

    def test_calculate_risk_score_velocity(self, risk_scorer, registered_customer, transaction_record):
        customer_id = registered_customer.customer_id
        for i in range(6):
            tx = TransactionRecord(
                transaction_id=uuid4(),
                customer_id=customer_id,
                amount=Decimal("10000"),
                currency="IDR",
                transaction_type=TransactionType.DEPOSIT,
                timestamp=datetime.utcnow() - timedelta(minutes=i*5),
                counterparty_name="test",
                payment_method="bank_transfer",
            )
            risk_scorer._transaction_history.setdefault(customer_id, []).append(tx)
        score = risk_scorer.calculate_risk_score(registered_customer, transaction_record)
        # Velocity: 6 txs in last hour => (6-5)*5 = 5
        # Base: 15 (amount) + 10 (tenure) + 5 (round) = 30, plus 5 = 35
        assert score == 35

    def test_calculate_risk_score_round_amount(self, risk_scorer, registered_customer, transaction_record):
        transaction_record.amount = Decimal("123456789")  # not round
        score = risk_scorer.calculate_risk_score(registered_customer, transaction_record)
        # No round bonus: 15 (amount) + 10 (tenure) = 25
        assert score == 25

    # ---- _check_transaction_velocity ----
    def test_check_transaction_velocity(self, risk_scorer, registered_customer):
        customer_id = registered_customer.customer_id
        now = datetime.utcnow()
        for i in range(3):
            tx = TransactionRecord(
                transaction_id=uuid4(),
                customer_id=customer_id,
                amount=Decimal("10000"),
                currency="IDR",
                transaction_type=TransactionType.DEPOSIT,
                timestamp=now - timedelta(minutes=i*10),
                counterparty_name="test",
                payment_method="bank_transfer",
            )
            risk_scorer._transaction_history.setdefault(customer_id, []).append(tx)
        old_tx = TransactionRecord(
            transaction_id=uuid4(),
            customer_id=customer_id,
            amount=Decimal("10000"),
            currency="IDR",
            transaction_type=TransactionType.DEPOSIT,
            timestamp=now - timedelta(hours=2),
            counterparty_name="test",
            payment_method="bank_transfer",
        )
        risk_scorer._transaction_history[customer_id].append(old_tx)
        velocity = risk_scorer._check_transaction_velocity(customer_id, now)
        assert velocity == 3  # only the 3 within last hour

    # ---- _is_round_amount ----
    def test_is_round_amount(self, risk_scorer):
        assert risk_scorer._is_round_amount(Decimal("1000000")) is True
        assert risk_scorer._is_round_amount(Decimal("1000000.00")) is True
        assert risk_scorer._is_round_amount(Decimal("1234567")) is False
        assert risk_scorer._is_round_amount(Decimal("1500000")) is True
        assert risk_scorer._is_round_amount(Decimal("123456.78")) is False

    # ---- get_risk_level ----
    def test_get_risk_level(self, risk_scorer):
        assert risk_scorer.get_risk_level(5) == RiskLevel.LOW
        assert risk_scorer.get_risk_level(30) == RiskLevel.MEDIUM
        assert risk_scorer.get_risk_level(60) == RiskLevel.HIGH
        assert risk_scorer.get_risk_level(80) == RiskLevel.CRITICAL
        assert risk_scorer.get_risk_level(100) == RiskLevel.CRITICAL

    # ---- calculate (simplified) ----
    def test_calculate_method(self, risk_scorer):
        result = risk_scorer.calculate(
            amount=Decimal("200000000"),
            country="AF",
            customer_tenure_years=0.5,
            payment_method="cash"
        )
        # Amount 200M => 15 points
        # Country AF high risk => 25 points
        # Tenure <1 year => 20 points
        # Payment cash => 15 points
        # Total = 75 => HIGH (60-79)
        assert result.score == 75
        assert result.risk_level == RiskLevel.HIGH
        assert result.requires_edd is True

    def test_calculate_method_no_edd(self, risk_scorer):
        result = risk_scorer.calculate(
            amount=Decimal("50000000"),
            country="ID",
            customer_tenure_years=5,
            payment_method="bank_transfer"
        )
        # Amount 50M => 5 points, country not high, tenure >3 => 0, payment no bonus => 0, total 5 => LOW, EDD false
        assert result.score == 5
        assert result.risk_level == RiskLevel.LOW
        assert result.requires_edd is False

    # ---- evaluate_edd_requirement ----
    def test_evaluate_edd_requirement_score_high(self, risk_scorer, registered_customer):
        assert risk_scorer.evaluate_edd_requirement(registered_customer, 60) is True
        assert risk_scorer.evaluate_edd_requirement(registered_customer, 50) is False

    def test_evaluate_edd_requirement_pep(self, risk_scorer, registered_customer):
        registered_customer.is_pep = True
        assert risk_scorer.evaluate_edd_requirement(registered_customer, 40) is True

    def test_evaluate_edd_requirement_high_risk_country(self, risk_scorer, registered_customer):
        registered_customer.country_code = "AF"
        assert risk_scorer.evaluate_edd_requirement(registered_customer, 40) is True

    def test_evaluate_edd_requirement_previous_str(self, risk_scorer, registered_customer):
        registered_customer.previous_str_count = 2
        assert risk_scorer.evaluate_edd_requirement(registered_customer, 40) is True

    def test_evaluate_edd_requirement_new_customer_large_amount(self, risk_scorer, registered_customer):
        registered_customer.registration_date = date.today() - timedelta(days=100)
        assert risk_scorer.evaluate_edd_requirement(registered_customer, 40, amount=Decimal("600000000")) is True
        assert risk_scorer.evaluate_edd_requirement(registered_customer, 40, amount=Decimal("400000000")) is False

    # ---- process_transaction ----
    def test_process_transaction_no_str(self, risk_scorer):
        transaction_data = {
            "amount": Decimal("100000000"),
            "business_justification": "Valid reason",
        }
        risk_scorer.process_transaction(transaction_data)  # should not raise

    def test_process_transaction_str_raised(self, risk_scorer):
        transaction_data = {
            "amount": Decimal("600000000"),
            "business_justification": None,
        }
        with pytest.raises(SuspiciousTransactionReported, match="Suspicious transaction detected"):
            risk_scorer.process_transaction(transaction_data)

    # ---- report_suspicious ----
    def test_report_suspicious(self, risk_scorer):
        report = risk_scorer.report_suspicious("tx-123", "Reason")
        assert report.submission_deadline == date.today() + timedelta(days=3)

    # ---- start_edd, submit_edd_document, complete_edd ----
    def test_start_edd(self, risk_scorer, registered_customer):
        customer_id = registered_customer.customer_id
        workflow = risk_scorer.start_edd(customer_id, uuid4())
        assert workflow["status"] == "in_progress"
        assert registered_customer.edd_status == EDDStatus.IN_PROGRESS
        assert "required_documents" in workflow

    def test_start_edd_already_completed(self, risk_scorer, registered_customer):
        registered_customer.edd_status = EDDStatus.COMPLETED
        result = risk_scorer.start_edd(registered_customer.customer_id, uuid4())
        assert result["status"] == "already_completed"

    def test_start_edd_customer_not_found(self, risk_scorer):
        with pytest.raises(AMLError, match="Customer .* not found"):
            risk_scorer.start_edd(uuid4(), uuid4())

    def test_submit_edd_document(self, risk_scorer, registered_customer):
        customer_id = registered_customer.customer_id
        risk_scorer.start_edd(customer_id, uuid4())
        risk_scorer.submit_edd_document(customer_id, "source_of_wealth", "http://doc.url")
        workflow = risk_scorer._edd_workflows[customer_id]
        assert len(workflow["submitted_documents"]) == 1
        assert workflow["submitted_documents"][0]["type"] == "source_of_wealth"

    def test_submit_edd_document_no_active_workflow(self, risk_scorer, registered_customer):
        with pytest.raises(AMLError, match="No active EDD workflow"):
            risk_scorer.submit_edd_document(registered_customer.customer_id, "type", "url")

    def test_complete_edd(self, risk_scorer, registered_customer):
        customer_id = registered_customer.customer_id
        risk_scorer.start_edd(customer_id, uuid4())
        result = risk_scorer.complete_edd(customer_id, uuid4(), "approved", "All good")
        assert result is True
        workflow = risk_scorer._edd_workflows[customer_id]
        assert workflow["status"] == "completed"
        assert workflow["decision"] == "approved"
        assert registered_customer.edd_status == EDDStatus.COMPLETED
        assert registered_customer.is_pep is False
        assert registered_customer.previous_str_count == 0

    def test_complete_edd_rejected(self, risk_scorer, registered_customer):
        customer_id = registered_customer.customer_id
        risk_scorer.start_edd(customer_id, uuid4())
        risk_scorer.complete_edd(customer_id, uuid4(), "rejected", "Risk too high")
        assert registered_customer.risk_level_cached == RiskLevel.CRITICAL

    def test_complete_edd_no_workflow(self, risk_scorer):
        assert risk_scorer.complete_edd(uuid4(), uuid4(), "approved", "") is False

    # ---- analyze_transaction ----
    def test_analyze_transaction_no_str(self, risk_scorer, registered_customer, transaction_record):
        report = risk_scorer.analyze_transaction(transaction_record)
        assert report is None
        assert len(risk_scorer._transaction_history[registered_customer.customer_id]) == 1
        assert registered_customer.risk_score_cached > 0
        assert registered_customer.last_assessment_date is not None

    def test_analyze_transaction_with_str(self, risk_scorer, registered_customer, transaction_record):
        transaction_record.amount = Decimal("2000000000")
        transaction_record.counterparty_country = "AF"
        registered_customer.is_pep = True
        report = risk_scorer.analyze_transaction(transaction_record)
        assert report is not None
        assert isinstance(report, SuspiciousTransactionReport)
        assert report.risk_level in (RiskLevel.CRITICAL, RiskLevel.HIGH)
        assert len(report.reasons) > 0
        assert registered_customer.previous_str_count == 1
        assert report in risk_scorer._str_reports

    def test_analyze_transaction_customer_not_found(self, risk_scorer, transaction_record):
        with pytest.raises(AMLError, match="Customer .* not registered"):
            risk_scorer.analyze_transaction(transaction_record)

    def test_analyze_transaction_edd_trigger(self, risk_scorer, registered_customer, transaction_record):
        registered_customer.is_pep = True
        transaction_record.amount = Decimal("2000000000")
        assert registered_customer.edd_status == EDDStatus.NOT_REQUIRED
        report = risk_scorer.analyze_transaction(transaction_record)
        assert registered_customer.edd_status == EDDStatus.IN_PROGRESS
        assert risk_scorer._edd_workflows[registered_customer.customer_id] is not None

    # ---- get_pending_str_reports ----
    def test_get_pending_str_reports(self, risk_scorer):
        report1 = SuspiciousTransactionReport(
            report_id=uuid4(),
            transaction_id=uuid4(),
            reporter_id=uuid4(),
            amount=Decimal("100"),
            currency="IDR",
            date=datetime.utcnow(),
            risk_score=80,
            risk_level=RiskLevel.CRITICAL,
            reasons=["test"],
        )
        report2 = SuspiciousTransactionReport(
            report_id=uuid4(),
            transaction_id=uuid4(),
            reporter_id=uuid4(),
            amount=Decimal("100"),
            currency="IDR",
            date=datetime.utcnow(),
            risk_score=80,
            risk_level=RiskLevel.CRITICAL,
            reasons=["test"],
            submitted_at=datetime.utcnow(),
        )
        risk_scorer._str_reports.extend([report1, report2])
        pending = risk_scorer.get_pending_str_reports()
        assert len(pending) == 1
        assert pending[0] == report1

    # ---- submit_all_str ----
    def test_submit_all_str(self, risk_scorer):
        report1 = SuspiciousTransactionReport(
            report_id=uuid4(),
            transaction_id=uuid4(),
            reporter_id=uuid4(),
            amount=Decimal("100"),
            currency="IDR",
            date=datetime.utcnow(),
            risk_score=80,
            risk_level=RiskLevel.CRITICAL,
            reasons=["test"],
        )
        report2 = SuspiciousTransactionReport(
            report_id=uuid4(),
            transaction_id=uuid4(),
            reporter_id=uuid4(),
            amount=Decimal("100"),
            currency="IDR",
            date=datetime.utcnow(),
            risk_score=80,
            risk_level=RiskLevel.CRITICAL,
            reasons=["test"],
        )
        risk_scorer._str_reports.extend([report1, report2])
        with patch.object(report1, "submit", return_value=True) as mock_submit1:
            with patch.object(report2, "submit", return_value=True) as mock_submit2:
                count = risk_scorer.submit_all_str()
                assert count == 2
                mock_submit1.assert_called_once()
                mock_submit2.assert_called_once()

    # ---- get_str_summary ----
    def test_get_str_summary(self, risk_scorer):
        report1 = SuspiciousTransactionReport(
            report_id=uuid4(),
            transaction_id=uuid4(),
            reporter_id=uuid4(),
            amount=Decimal("100"),
            currency="IDR",
            date=datetime.utcnow(),
            risk_score=80,
            risk_level=RiskLevel.CRITICAL,
            reasons=["test"],
        )
        report2 = SuspiciousTransactionReport(
            report_id=uuid4(),
            transaction_id=uuid4(),
            reporter_id=uuid4(),
            amount=Decimal("100"),
            currency="IDR",
            date=datetime.utcnow(),
            risk_score=80,
            risk_level=RiskLevel.CRITICAL,
            reasons=["test"],
            submitted_at=datetime.utcnow(),
        )
        risk_scorer._str_reports.extend([report1, report2])
        summary = risk_scorer.get_str_summary()
        assert summary["total_str_generated"] == 2
        assert summary["pending_submission"] == 1
        assert summary["submitted"] == 1
        assert summary["by_risk_level"]["critical"] == 2

    # ---- generate_compliance_report ----
    def test_generate_compliance_report(self, risk_scorer):
        now = datetime.utcnow()
        report1 = SuspiciousTransactionReport(
            report_id=uuid4(),
            transaction_id=uuid4(),
            reporter_id=uuid4(),
            amount=Decimal("100"),
            currency="IDR",
            date=now - timedelta(days=5),
            risk_score=80,
            risk_level=RiskLevel.CRITICAL,
            reasons=["test"],
            submitted_at=now - timedelta(days=5),
        )
        report2 = SuspiciousTransactionReport(
            report_id=uuid4(),
            transaction_id=uuid4(),
            reporter_id=uuid4(),
            amount=Decimal("100"),
            currency="IDR",
            date=now - timedelta(days=20),
            risk_score=70,
            risk_level=RiskLevel.HIGH,
            reasons=["test"],
        )
        risk_scorer._str_reports.extend([report1, report2])
        start_date = (now - timedelta(days=10)).date()
        end_date = now.date()
        compliance_report = risk_scorer.generate_compliance_report(start_date, end_date)
        assert compliance_report["str_count"] == 1
        assert compliance_report["period_start"] == start_date.isoformat()
        assert compliance_report["period_end"] == end_date.isoformat()
        assert compliance_report["edd_cases"] == 0
        assert compliance_report["average_risk_score"] == 80.0

    # ---- edge: str report submit with client ----
    def test_submit_all_str_with_client(self, risk_scorer, ppatk_client):
        report = SuspiciousTransactionReport(
            report_id=uuid4(),
            transaction_id=uuid4(),
            reporter_id=uuid4(),
            amount=Decimal("100"),
            currency="IDR",
            date=datetime.utcnow(),
            risk_score=80,
            risk_level=RiskLevel.CRITICAL,
            reasons=["test"],
        )
        risk_scorer._str_reports.append(report)
        with patch.object(report, "submit", return_value=True) as mock_submit:
            count = risk_scorer.submit_all_str()
            mock_submit.assert_called_once_with(risk_scorer._ppatk_client)
            assert count == 1

    # ---- test SuspiciousTransactionReported exception in process_transaction ----
    def test_process_transaction_raises_exception(self, risk_scorer):
        with pytest.raises(SuspiciousTransactionReported) as excinfo:
            risk_scorer.process_transaction({"amount": Decimal("600000000"), "business_justification": None})
        assert "Suspicious transaction detected" in str(excinfo.value)
        assert excinfo.value.report_id == "STR-001"
        assert excinfo.value.destination == "PPATK"

    # ---- test AMLError raised in update_customer_profile ----
    def test_update_customer_profile_raises_amlerror(self, risk_scorer):
        with pytest.raises(AMLError, match="Customer .* not found"):
            risk_scorer.update_customer_profile(uuid4())

    # ---- test SanctionListUnavailableError and STRSubmissionError ----
    # These exceptions are defined but not raised in code; they are used in imports and maybe future.
    # We can just instantiate them for coverage.
    def test_exceptions_instantiable(self):
        e1 = SanctionListUnavailableError("msg")
        assert str(e1) == "msg"
        e2 = STRSubmissionError("msg")
        assert str(e2) == "msg"
        e3 = AMLError("msg")
        assert str(e3) == "msg"
