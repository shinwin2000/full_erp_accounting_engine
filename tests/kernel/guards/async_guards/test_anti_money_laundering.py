# tests/kernel/guards/async_guards/test_anti_money_laundering.py
# Perbaikan kualitas assertions: semua assert True dihapus,
# diganti dengan assertion yang memeriksa nilai aktual,
# efek samping, atau interaksi mock.
# Juga perbaikan flakiness: datetime.now(UTC) diganti dengan fixed datetime.
# Duplikat test digabung dengan parametrize.
# Semua async test diberi marker @pytest.mark.asyncio.

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from kernel.guards.async_guards.anti_money_laundering import (
    HIGH_RISK_COUNTRIES,
    MONITORED_COUNTRIES,
    AMLAlert,
    AMLAlertType,
    AMLScore,
    AMLScoreLevel,
    AMLScreeningResult,
    AntiMoneyLaunderingEngine,
    AntiMoneyLaunderingGuard,
    _FallbackCustomerRepository,
    _FallbackTransactionRepository,
    get_anti_money_laundering_engine,
    get_anti_money_laundering_guard,
)

# Helper fixed datetime to avoid flakiness
FIXED_NOW = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)


# ============================================================================
# _FallbackTransactionRepository tests
# ============================================================================
class TestFallbackTransactionRepository:
    @pytest.fixture
    def repo(self):
        return _FallbackTransactionRepository()

    @pytest.fixture
    def customer_id(self):
        return uuid4()

    @pytest.fixture
    def legal_entity_id(self):
        return uuid4()

    @pytest.mark.asyncio
    async def test_record_and_get_by_customer(self, repo, customer_id, legal_entity_id):
        tx_id = uuid4()
        now = FIXED_NOW
        await repo.record_transaction(
            transaction_id=tx_id,
            customer_id=customer_id,
            legal_entity_id=legal_entity_id,
            amount=Decimal("1000"),
            transaction_date=now,
            transaction_type="DEPOSIT",
        )
        tx_id2 = uuid4()
        await repo.record_transaction(
            transaction_id=tx_id2,
            customer_id=customer_id,
            legal_entity_id=legal_entity_id,
            amount=Decimal("500"),
            transaction_date=now - timedelta(hours=2),
            transaction_type="WITHDRAWAL",
        )

        result = await repo.get_by_customer(
            customer_id=customer_id,
            legal_entity_id=legal_entity_id,
            from_date=now - timedelta(days=1),
            to_date=now + timedelta(days=1),
        )
        assert len(result) == 2
        assert result[0].amount == Decimal("1000")
        assert result[0].transaction_type == "DEPOSIT"
        result_deposit = await repo.get_by_customer(
            customer_id=customer_id,
            legal_entity_id=legal_entity_id,
            from_date=now - timedelta(days=1),
            transaction_type="DEPOSIT",
        )
        assert len(result_deposit) == 1
        assert result_deposit[0].amount == Decimal("1000")

    @pytest.mark.asyncio
    async def test_get_average_daily_volume(self, repo, customer_id, legal_entity_id):
        now = FIXED_NOW
        for i in range(3):
            day_date = now - timedelta(days=i)
            for _ in range(2):
                await repo.record_transaction(
                    transaction_id=uuid4(),
                    customer_id=customer_id,
                    legal_entity_id=legal_entity_id,
                    amount=Decimal("1000") * (i + 1),
                    transaction_date=day_date,
                    transaction_type="DEPOSIT",
                )
        avg = await repo.get_average_daily_volume(customer_id, legal_entity_id, days=3)
        assert avg == Decimal("4000")

    @pytest.mark.asyncio
    async def test_get_circular_transfers(self, repo, customer_id):
        result = await repo.get_circular_transfers(customer_id, ["acc1"], FIXED_NOW)
        assert result == []

    @pytest.mark.asyncio
    async def test_get_accounts_by_customer(self, repo, customer_id, legal_entity_id):
        result = await repo.get_accounts_by_customer(customer_id, legal_entity_id)
        assert result == []

    @pytest.mark.asyncio
    async def test_reset(self, repo, customer_id, legal_entity_id):
        await repo.record_transaction(
            transaction_id=uuid4(),
            customer_id=customer_id,
            legal_entity_id=legal_entity_id,
            amount=Decimal("1000"),
            transaction_date=FIXED_NOW,
            transaction_type="DEPOSIT",
        )
        repo.reset()
        result = await repo.get_by_customer(customer_id, legal_entity_id, FIXED_NOW - timedelta(days=1))
        assert result == []
        assert len(repo._daily_volumes) == 0


# ============================================================================
# _FallbackCustomerRepository tests
# ============================================================================
class TestFallbackCustomerRepository:
    @pytest.fixture
    def repo(self):
        return _FallbackCustomerRepository()

    @pytest.mark.asyncio
    async def test_add_and_get_by_id(self, repo):
        customer_id = uuid4()
        legal_entity_id = uuid4()
        repo.add_customer(customer_id, legal_entity_id, name="John", risk_rating="high", country_code="ID")
        customer = await repo.get_by_id(customer_id, legal_entity_id)
        assert customer is not None
        assert customer.id == customer_id
        assert customer.name == "John"
        assert customer.risk_rating == "high"
        assert customer.country_code == "ID"
        other_legal = uuid4()
        customer2 = await repo.get_by_id(customer_id, other_legal)
        assert customer2 is None


# ============================================================================
# Enum tests
# ============================================================================
class TestAMLScoreLevel:
    def test_members(self):
        assert hasattr(AMLScoreLevel, "LOW")
        assert hasattr(AMLScoreLevel, "MEDIUM")
        assert hasattr(AMLScoreLevel, "HIGH")
        assert hasattr(AMLScoreLevel, "CRITICAL")
        assert AMLScoreLevel.LOW.value == 20
        assert AMLScoreLevel.MEDIUM.value == 40


class TestAMLAlertType:
    def test_members(self):
        expected = [
            "LARGE_TRANSACTION",
            "RAPID_SUCCESSION",
            "HIGH_RISK_COUNTRY",
            "UNUSUAL_PATTERN",
            "STRUCTURING",
            "RAPID_CASH_OUT",
            "CURRENCY_EXCHANGE_ANOMALY",
            "RELATED_PARTY_RING",
        ]
        for name in expected:
            assert hasattr(AMLAlertType, name)


# ============================================================================
# AMLScore tests
# ============================================================================
class TestAMLScore:
    def test_create_and_hash(self):
        score_id = uuid4()
        tx_id = uuid4()
        cust_id = uuid4()
        legal_id = uuid4()
        now = FIXED_NOW
        score = AMLScore(
            score_id=score_id,
            transaction_id=tx_id,
            customer_id=cust_id,
            legal_entity_id=legal_id,
            score=75.0,
            level=AMLScoreLevel.HIGH,
            factors=["large amount", "high risk country"],
            detected_at=now,
            threshold_exceeded=True,
            cryptographic_hash="",
        )
        computed = score.compute_hash()
        score2 = AMLScore(
            score_id=score_id,
            transaction_id=tx_id,
            customer_id=cust_id,
            legal_entity_id=legal_id,
            score=75.0,
            level=AMLScoreLevel.HIGH,
            factors=["large amount", "high risk country"],
            detected_at=now,
            threshold_exceeded=True,
            cryptographic_hash=computed,
        )
        assert score2.cryptographic_hash == computed
        with pytest.raises(ValueError, match="hash mismatch"):
            AMLScore(
                score_id=score_id,
                transaction_id=tx_id,
                customer_id=cust_id,
                legal_entity_id=legal_id,
                score=75.0,
                level=AMLScoreLevel.HIGH,
                factors=["large amount", "high risk country"],
                detected_at=now,
                threshold_exceeded=True,
                cryptographic_hash="invalid",
            )

    def test_to_dict(self):
        score_id = uuid4()
        tx_id = uuid4()
        cust_id = uuid4()
        legal_id = uuid4()
        now = FIXED_NOW
        score = AMLScore(
            score_id=score_id,
            transaction_id=tx_id,
            customer_id=cust_id,
            legal_entity_id=legal_id,
            score=75.0,
            level=AMLScoreLevel.HIGH,
            factors=["factor1"],
            detected_at=now,
            threshold_exceeded=True,
            cryptographic_hash="abc",
        )
        d = score.to_dict()
        assert d["score_id"] == str(score_id)
        assert d["score"] == 75.0
        assert d["level"] == "HIGH"
        assert d["factors"] == ["factor1"]


# ============================================================================
# AMLAlert tests
# ============================================================================
class TestAMLAlert:
    def test_create_and_hash(self):
        alert_id = uuid4()
        tx_id = uuid4()
        cust_id = uuid4()
        now = FIXED_NOW
        alert = AMLAlert(
            alert_id=alert_id,
            transaction_id=tx_id,
            customer_id=cust_id,
            alert_type=AMLAlertType.LARGE_TRANSACTION,
            severity=AMLScoreLevel.MEDIUM,
            description="Large transaction detected",
            detected_at=now,
            score=60.0,
            supporting_data={"amount": "1000000"},
            acknowledged=False,
            acknowledged_by=None,
            acknowledged_at=None,
            reported_to_fiu=False,
            cryptographic_hash="",
        )
        computed = alert.compute_hash()
        alert2 = AMLAlert(
            alert_id=alert_id,
            transaction_id=tx_id,
            customer_id=cust_id,
            alert_type=AMLAlertType.LARGE_TRANSACTION,
            severity=AMLScoreLevel.MEDIUM,
            description="Large transaction detected",
            detected_at=now,
            score=60.0,
            supporting_data={"amount": "1000000"},
            acknowledged=False,
            acknowledged_by=None,
            acknowledged_at=None,
            reported_to_fiu=False,
            cryptographic_hash=computed,
        )
        assert alert2.cryptographic_hash == computed
        with pytest.raises(ValueError):
            AMLAlert(
                alert_id=alert_id,
                transaction_id=tx_id,
                customer_id=cust_id,
                alert_type=AMLAlertType.LARGE_TRANSACTION,
                severity=AMLScoreLevel.MEDIUM,
                description="Large transaction detected",
                detected_at=now,
                score=60.0,
                supporting_data={"amount": "1000000"},
                acknowledged=False,
                acknowledged_by=None,
                acknowledged_at=None,
                reported_to_fiu=False,
                cryptographic_hash="invalid",
            )

    def test_acknowledge(self):
        alert_id = uuid4()
        tx_id = uuid4()
        cust_id = uuid4()
        now = FIXED_NOW
        alert = AMLAlert(
            alert_id=alert_id,
            transaction_id=tx_id,
            customer_id=cust_id,
            alert_type=AMLAlertType.LARGE_TRANSACTION,
            severity=AMLScoreLevel.MEDIUM,
            description="Large transaction detected",
            detected_at=now,
            score=60.0,
            supporting_data={},
            acknowledged=False,
            reported_to_fiu=False,
            cryptographic_hash="",
        )
        ack_alert = alert.acknowledge("admin")
        assert ack_alert.acknowledged is True
        assert ack_alert.acknowledged_by == "admin"
        assert ack_alert.acknowledged_at is not None
        assert ack_alert.alert_id == alert_id

    def test_to_dict(self):
        alert_id = uuid4()
        tx_id = uuid4()
        cust_id = uuid4()
        now = FIXED_NOW
        alert = AMLAlert(
            alert_id=alert_id,
            transaction_id=tx_id,
            customer_id=cust_id,
            alert_type=AMLAlertType.LARGE_TRANSACTION,
            severity=AMLScoreLevel.MEDIUM,
            description="Large transaction detected",
            detected_at=now,
            score=60.0,
            supporting_data={},
            acknowledged=True,
            reported_to_fiu=True,
            cryptographic_hash="",
        )
        d = alert.to_dict()
        assert d["alert_id"] == str(alert_id)
        assert d["alert_type"] == "LARGE_TRANSACTION"
        assert d["severity"] == "MEDIUM"
        assert d["acknowledged"] is True
        assert d["reported_to_fiu"] is True


# ============================================================================
# AMLScreeningResult tests
# ============================================================================
class TestAMLScreeningResult:
    def test_creation(self):
        result = AMLScreeningResult(
            is_flagged=True,
            threshold_exceeded=True,
            reasons=["reason1"],
            sar_id="SAR-123",
        )
        assert result.is_flagged is True
        assert result.threshold_exceeded is True
        assert result.reasons == ["reason1"]
        assert result.sar_id == "SAR-123"


# ============================================================================
# AntiMoneyLaunderingEngine tests
# ============================================================================
class TestAntiMoneyLaunderingEngine:
    @pytest.fixture
    def engine(self):
        return AntiMoneyLaunderingEngine()

    @pytest.fixture
    def customer_id(self):
        return uuid4()

    @pytest.fixture
    def legal_entity_id(self):
        return uuid4()

    def test_enable(self, engine):
        assert engine._enabled is True
        engine.enable(False)
        assert engine._enabled is False
        engine.enable(True)
        assert engine._enabled is True

    def test_set_thresholds(self, engine):
        engine.set_thresholds(Decimal("1000000"), Decimal("500000"), 7)
        assert engine._large_transaction_threshold == Decimal("1000000")
        assert engine._structuring_threshold == Decimal("500000")
        assert engine._structuring_window_days == 7

    @pytest.mark.asyncio
    async def test_calculate_risk_score_disabled(self, engine, customer_id, legal_entity_id):
        engine.enable(False)
        tx_id = uuid4()
        now = FIXED_NOW
        score = await engine.calculate_risk_score(
            transaction_id=tx_id,
            customer_id=customer_id,
            amount=Decimal("1000000000"),
            currency="IDR",
            transaction_date=now,
            legal_entity_id=legal_entity_id,
            country_code="US",
        )
        assert score.score == 0.0
        assert score.level == AMLScoreLevel.LOW
        assert "disabled" in score.factors[0]

    @pytest.mark.asyncio
    async def test_calculate_risk_score_large(self, engine, customer_id, legal_entity_id):
        engine._large_transaction_threshold = Decimal("1000000")
        tx_id = uuid4()
        now = FIXED_NOW
        score = await engine.calculate_risk_score(
            transaction_id=tx_id,
            customer_id=customer_id,
            amount=Decimal("2000000"),
            currency="IDR",
            transaction_date=now,
            legal_entity_id=legal_entity_id,
            country_code="US",
        )
        assert score.score == 40.0
        assert score.level == AMLScoreLevel.MEDIUM
        assert "exceeds large transaction threshold" in score.factors[0]

    @pytest.mark.asyncio
    async def test_calculate_risk_score_high_risk_country(self, engine, customer_id, legal_entity_id):
        engine._large_transaction_threshold = Decimal("1000000")
        tx_id = uuid4()
        now = FIXED_NOW
        country = next(iter(HIGH_RISK_COUNTRIES))
        score = await engine.calculate_risk_score(
            transaction_id=tx_id,
            customer_id=customer_id,
            amount=Decimal("500000"),
            currency="IDR",
            transaction_date=now,
            legal_entity_id=legal_entity_id,
            country_code=country,
        )
        assert score.score == 30.0
        assert score.level == AMLScoreLevel.MEDIUM
        assert f"high-risk country: {country}" in score.factors[0]

    @pytest.mark.asyncio
    async def test_calculate_risk_score_monitored_country(self, engine, customer_id, legal_entity_id):
        country = next(iter(MONITORED_COUNTRIES))
        tx_id = uuid4()
        now = FIXED_NOW
        score = await engine.calculate_risk_score(
            transaction_id=tx_id,
            customer_id=customer_id,
            amount=Decimal("500000"),
            currency="IDR",
            transaction_date=now,
            legal_entity_id=legal_entity_id,
            country_code=country,
        )
        assert score.score == 15.0
        assert score.level == AMLScoreLevel.LOW
        assert f"monitored country: {country}" in score.factors[0]

    @pytest.mark.asyncio
    async def test_calculate_risk_score_foreign_currency(self, engine, customer_id, legal_entity_id):
        tx_id = uuid4()
        now = FIXED_NOW
        score = await engine.calculate_risk_score(
            transaction_id=tx_id,
            customer_id=customer_id,
            amount=Decimal("500000"),
            currency="USD",
            transaction_date=now,
            legal_entity_id=legal_entity_id,
            country_code="SG",
        )
        assert score.score == 10.0
        assert "foreign currency: USD" in score.factors[0]

    @pytest.mark.asyncio
    async def test_calculate_risk_score_rapid_succession(self, engine, customer_id, legal_entity_id):
        now = FIXED_NOW
        for i in range(4):
            await engine._tx_repo.record_transaction(
                transaction_id=uuid4(),
                customer_id=customer_id,
                legal_entity_id=legal_entity_id,
                amount=Decimal("1000"),
                transaction_date=now - timedelta(hours=i),
                transaction_type="DEPOSIT",
            )
        tx_id = uuid4()
        score = await engine.calculate_risk_score(
            transaction_id=tx_id,
            customer_id=customer_id,
            amount=Decimal("1000"),
            currency="IDR",
            transaction_date=now,
            legal_entity_id=legal_entity_id,
            country_code=None,
        )
        assert score.score == 20.0
        assert "Rapid succession: 4 transactions in 24h" in score.factors[0]

    @pytest.mark.asyncio
    async def test_calculate_risk_score_volume_spike(self, engine, customer_id, legal_entity_id):
        now = FIXED_NOW
        for day in range(30):
            for _ in range(2):
                await engine._tx_repo.record_transaction(
                    transaction_id=uuid4(),
                    customer_id=customer_id,
                    legal_entity_id=legal_entity_id,
                    amount=Decimal("1000"),
                    transaction_date=now - timedelta(days=day),
                    transaction_type="DEPOSIT",
                )
        tx_id = uuid4()
        score = await engine.calculate_risk_score(
            transaction_id=tx_id,
            customer_id=customer_id,
            amount=Decimal("20000"),
            currency="IDR",
            transaction_date=now,
            legal_entity_id=legal_entity_id,
            country_code=None,
        )
        assert score.score == 15.0
        assert "Volume spike: 10.0x normal" in score.factors[0]

    @pytest.mark.asyncio
    async def test_detect_structuring(self, engine, customer_id, legal_entity_id):
        engine._structuring_threshold = Decimal("1000000")
        engine._structuring_small_pct = Decimal("0.9")
        now = FIXED_NOW
        for i in range(4):
            amount = Decimal("900000")
            await engine._tx_repo.record_transaction(
                transaction_id=uuid4(),
                customer_id=customer_id,
                legal_entity_id=legal_entity_id,
                amount=amount,
                transaction_date=now - timedelta(days=i),
                transaction_type="DEPOSIT",
            )
        alert = await engine.detect_structuring(
            transaction_id=uuid4(),
            customer_id=customer_id,
            amount=Decimal("900000"),
            legal_entity_id=legal_entity_id,
            transaction_date=now,
        )
        assert alert is not None
        assert alert.alert_type == AMLAlertType.STRUCTURING
        assert alert.severity == AMLScoreLevel.HIGH
        assert "Structuring detected" in alert.description
        assert alert.supporting_data["transaction_count"] == 4
        assert Decimal(alert.supporting_data["total_amount"]) == Decimal("3600000")

    @pytest.mark.asyncio
    async def test_detect_structuring_not_enough(self, engine, customer_id, legal_entity_id):
        engine._structuring_threshold = Decimal("1000000")
        now = FIXED_NOW
        for i in range(2):
            await engine._tx_repo.record_transaction(
                transaction_id=uuid4(),
                customer_id=customer_id,
                legal_entity_id=legal_entity_id,
                amount=Decimal("900000"),
                transaction_date=now - timedelta(days=i),
                transaction_type="DEPOSIT",
            )
        alert = await engine.detect_structuring(
            transaction_id=uuid4(),
            customer_id=customer_id,
            amount=Decimal("900000"),
            legal_entity_id=legal_entity_id,
            transaction_date=now,
        )
        assert alert is None

    @pytest.mark.asyncio
    async def test_detect_rapid_cash_out(self, engine, customer_id, legal_entity_id):
        engine._large_transaction_threshold = Decimal("2000000")
        now = FIXED_NOW
        deposit_amount = Decimal("2000000")
        await engine._tx_repo.record_transaction(
            transaction_id=uuid4(),
            customer_id=customer_id,
            legal_entity_id=legal_entity_id,
            amount=deposit_amount,
            transaction_date=now - timedelta(hours=12),
            transaction_type="DEPOSIT",
        )
        withdrawal = deposit_amount * Decimal("0.6")
        alert = await engine.detect_rapid_cash_out(
            transaction_id=uuid4(),
            customer_id=customer_id,
            amount=withdrawal,
            transaction_date=now,
            legal_entity_id=legal_entity_id,
            is_withdrawal=True,
        )
        assert alert is not None
        assert alert.alert_type == AMLAlertType.RAPID_CASH_OUT
        assert alert.severity == AMLScoreLevel.MEDIUM
        assert "Rapid cash out" in alert.description
        assert alert.supporting_data["ratio"] == "0.6"

    @pytest.mark.asyncio
    async def test_detect_rapid_cash_out_high_ratio(self, engine, customer_id, legal_entity_id):
        engine._large_transaction_threshold = Decimal("2000000")
        now = FIXED_NOW
        deposit_amount = Decimal("2000000")
        await engine._tx_repo.record_transaction(
            transaction_id=uuid4(),
            customer_id=customer_id,
            legal_entity_id=legal_entity_id,
            amount=deposit_amount,
            transaction_date=now - timedelta(hours=12),
            transaction_type="DEPOSIT",
        )
        withdrawal = deposit_amount * Decimal("0.9")
        alert = await engine.detect_rapid_cash_out(
            transaction_id=uuid4(),
            customer_id=customer_id,
            amount=withdrawal,
            transaction_date=now,
            legal_entity_id=legal_entity_id,
            is_withdrawal=True,
        )
        assert alert is not None
        assert alert.severity == AMLScoreLevel.HIGH

    @pytest.mark.asyncio
    async def test_detect_rapid_cash_out_without_deposit(self, engine, customer_id, legal_entity_id):
        now = FIXED_NOW
        alert = await engine.detect_rapid_cash_out(
            transaction_id=uuid4(),
            customer_id=customer_id,
            amount=Decimal("1000000"),
            transaction_date=now,
            legal_entity_id=legal_entity_id,
            is_withdrawal=True,
        )
        assert alert is None

    @pytest.mark.asyncio
    async def test_analyze_transaction_full(self, engine, customer_id, legal_entity_id):
        engine._large_transaction_threshold = Decimal("1000000")
        engine._structuring_threshold = Decimal("1000000")
        now = FIXED_NOW
        for i in range(4):
            await engine._tx_repo.record_transaction(
                transaction_id=uuid4(),
                customer_id=customer_id,
                legal_entity_id=legal_entity_id,
                amount=Decimal("1000"),
                transaction_date=now - timedelta(hours=i),
                transaction_type="DEPOSIT",
            )
        tx_id = uuid4()
        score, alerts = await engine.analyze_transaction(
            transaction_id=tx_id,
            customer_id=customer_id,
            amount=Decimal("5000000"),
            currency="USD",
            transaction_date=now,
            legal_entity_id=legal_entity_id,
            is_withdrawal=False,
            country_code="AFG",
            transaction_type="DEPOSIT",
        )
        assert score.score == 100.0
        assert score.level == AMLScoreLevel.CRITICAL
        assert len(alerts) == 0
        txs = await engine._tx_repo.get_by_customer(customer_id, legal_entity_id, now - timedelta(days=1))
        assert any(tx.id == tx_id for tx in txs)

    def test_get_alerts(self, engine, customer_id):
        now = FIXED_NOW
        alert1 = AMLAlert(
            alert_id=uuid4(),
            transaction_id=uuid4(),
            customer_id=customer_id,
            alert_type=AMLAlertType.LARGE_TRANSACTION,
            severity=AMLScoreLevel.CRITICAL,
            description="critical",
            detected_at=now,
            score=80,
            supporting_data={},
            cryptographic_hash="",
        )
        alert2 = AMLAlert(
            alert_id=uuid4(),
            transaction_id=uuid4(),
            customer_id=customer_id,
            alert_type=AMLAlertType.STRUCTURING,
            severity=AMLScoreLevel.MEDIUM,
            description="medium",
            detected_at=now,
            score=40,
            supporting_data={},
            cryptographic_hash="",
        )
        engine._alerts = [alert1, alert2]
        criticals = engine.get_alerts(min_severity=AMLScoreLevel.CRITICAL)
        assert len(criticals) == 1
        assert criticals[0].severity == AMLScoreLevel.CRITICAL
        mediums = engine.get_alerts(min_severity=AMLScoreLevel.MEDIUM)
        assert len(mediums) == 2
        alert1_ack = alert1.acknowledge("admin")
        engine._alerts = [alert1_ack, alert2]
        acked = engine.get_alerts(acknowledged=True)
        assert len(acked) == 1
        assert acked[0].alert_id == alert1.alert_id
        unacked = engine.get_alerts(acknowledged=False)
        assert len(unacked) == 1
        assert unacked[0].alert_id == alert2.alert_id

    def test_get_statistics(self, engine, customer_id):
        now = FIXED_NOW
        engine._alerts = [
            AMLAlert(
                alert_id=uuid4(),
                transaction_id=uuid4(),
                customer_id=customer_id,
                alert_type=AMLAlertType.LARGE_TRANSACTION,
                severity=AMLScoreLevel.CRITICAL,
                description="c1",
                detected_at=now,
                score=80,
                supporting_data={},
                cryptographic_hash="",
            ),
            AMLAlert(
                alert_id=uuid4(),
                transaction_id=uuid4(),
                customer_id=customer_id,
                alert_type=AMLAlertType.STRUCTURING,
                severity=AMLScoreLevel.HIGH,
                description="h1",
                detected_at=now,
                score=60,
                supporting_data={},
                cryptographic_hash="",
                reported_to_fiu=True,
            ),
            AMLAlert(
                alert_id=uuid4(),
                transaction_id=uuid4(),
                customer_id=customer_id,
                alert_type=AMLAlertType.RAPID_CASH_OUT,
                severity=AMLScoreLevel.MEDIUM,
                description="m1",
                detected_at=now,
                score=40,
                supporting_data={},
                cryptographic_hash="",
            ),
        ]
        stats = engine.get_statistics()
        assert stats["total_alerts"] == 3
        assert stats["critical_alerts"] == 1
        assert stats["high_alerts"] == 1
        assert stats["reported_to_fiu"] == 1
        assert stats["enabled"] is True

    def test_acknowledge_alert(self, engine, customer_id):
        alert_id = uuid4()
        now = FIXED_NOW
        alert = AMLAlert(
            alert_id=alert_id,
            transaction_id=uuid4(),
            customer_id=customer_id,
            alert_type=AMLAlertType.LARGE_TRANSACTION,
            severity=AMLScoreLevel.CRITICAL,
            description="c1",
            detected_at=now,
            score=80,
            supporting_data={},
            cryptographic_hash="",
        )
        engine._alerts = [alert]
        acked = engine.acknowledge_alert(alert_id, "admin")
        assert acked is not None
        assert acked.acknowledged is True
        assert acked.acknowledged_by == "admin"
        acked2 = engine.acknowledge_alert(alert_id, "admin")
        assert acked2 is None

    def test_reset(self, engine, customer_id):
        engine._scores = [MagicMock()]
        engine._alerts = [MagicMock()]
        engine.reset()
        assert engine._scores == []
        assert engine._alerts == []
        assert engine._enabled is True
        if hasattr(engine._tx_repo, "reset"):
            with patch.object(engine._tx_repo, "reset") as mock_reset:
                engine.reset()
                mock_reset.assert_called_once()


# ============================================================================
# AntiMoneyLaunderingGuard tests
# ============================================================================
class TestAntiMoneyLaunderingGuard:
    @pytest.fixture
    def guard(self):
        return AntiMoneyLaunderingGuard()

    def test_enable(self, guard):
        assert guard._engine._enabled is True
        guard.enable(False)
        assert guard._engine._enabled is False
        guard.enable(True)
        assert guard._engine._enabled is True

    def test_set_thresholds(self, guard):
        guard.set_thresholds(Decimal("1000000"), Decimal("500000"), 7)
        assert guard._engine._large_transaction_threshold == Decimal("1000000")
        assert guard._engine._structuring_threshold == Decimal("500000")

    @pytest.mark.asyncio
    async def test_calculate_risk_score(self, guard):
        tx_id = uuid4()
        cust_id = uuid4()
        legal_id = uuid4()
        now = FIXED_NOW
        score = await guard.calculate_risk_score(
            transaction_id=tx_id,
            customer_id=cust_id,
            amount=Decimal("1000000000"),
            currency="IDR",
            transaction_date=now,
            legal_entity_id=legal_id,
            country_code="AFG",
        )
        assert isinstance(score, AMLScore)
        assert score.score > 0

    @pytest.mark.asyncio
    async def test_analyze_transaction(self, guard):
        tx_id = uuid4()
        cust_id = uuid4()
        legal_id = uuid4()
        now = FIXED_NOW
        score, alerts = await guard.analyze_transaction(
            transaction_id=tx_id,
            customer_id=cust_id,
            amount=Decimal("1000000000"),
            currency="IDR",
            transaction_date=now,
            legal_entity_id=legal_id,
            is_withdrawal=False,
            country_code="AFG",
            transaction_type="DEPOSIT",
        )
        assert isinstance(score, AMLScore)
        assert isinstance(alerts, list)

    # ---- screen method ----
    def test_screen_threshold_exceeded(self, guard):
        guard.reset_daily_totals()
        payment = {
            "amount": Decimal("150000000"),
            "from_account": "ACC001",
            "payment_date": date.today(),
            "beneficiary_name": "Normal Person",
        }
        result = guard.screen(payment)
        assert result.is_flagged is True
        assert result.threshold_exceeded is True
        assert "amount exceeds AML threshold" in result.reasons
        assert result.sar_id is not None

    def test_screen_structuring(self, guard):
        guard.reset_daily_totals()
        payment_date = date.today()
        payment1 = {
            "amount": Decimal("80000000"),
            "from_account": "ACC001",
            "payment_date": payment_date,
            "beneficiary_name": "Normal",
        }
        result1 = guard.screen(payment1)
        assert result1.is_flagged is False
        payment2 = {
            "amount": Decimal("80000000"),
            "from_account": "ACC001",
            "payment_date": payment_date,
            "beneficiary_name": "Normal",
        }
        result2 = guard.screen(payment2)
        assert result2.is_flagged is True
        assert "structuring pattern detected" in result2.reasons
        assert result2.threshold_exceeded is False

    def test_screen_sanction_list(self, guard):
        guard.reset_daily_totals()
        payment = {
            "amount": Decimal("50000000"),
            "from_account": "ACC001",
            "payment_date": date.today(),
            "beneficiary_name": "Sanctioned Person",
        }
        result = guard.screen(payment)
        assert result.is_flagged is True
        assert "sanction list hit" in result.reasons

    def test_screen_pep(self, guard):
        with patch.object(guard, "_is_pep", return_value=True):
            payment = {
                "amount": Decimal("50000000"),
                "from_account": "ACC001",
                "payment_date": date.today(),
                "beneficiary_name": "Politician",
            }
            result = guard.screen(payment)
            assert result.is_flagged is True
            assert "PEP" in result.reasons[0]

    def test_screen_no_flag(self, guard):
        guard.reset_daily_totals()
        payment = {
            "amount": Decimal("50000000"),
            "from_account": "ACC001",
            "payment_date": date.today(),
            "beneficiary_name": "Normal",
        }
        result = guard.screen(payment)
        assert result.is_flagged is False
        assert result.reasons == []
        assert result.sar_id is None

    def test_reset_daily_totals(self, guard):
        guard._daily_totals["ACC"] = Decimal("100")
        guard._last_date["ACC"] = date.today()
        guard.reset_daily_totals()
        assert guard._daily_totals == {}
        assert guard._last_date == {}

    # ---- check method ----
    @pytest.mark.asyncio
    async def test_check_valid(self, guard):
        context = {
            "transaction_id": uuid4(),
            "customer_id": uuid4(),
            "amount": "1000",
        }
        errors = await guard.check(context)
        assert errors == []

    @pytest.mark.asyncio
    async def test_check_missing_fields(self, guard):
        context = {}
        errors = await guard.check(context)
        assert "transaction_id is required" in errors
        assert "customer_id is required" in errors
        assert "amount is required" in errors

    # Combined duplicate test: test both invalid amount (negative and non-number)
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "amount, expected_error",
        [
            ("-100", "amount must be non-negative"),
            ("not_a_number", "amount must be a valid number"),
        ],
    )
    async def test_check_invalid_amount_combined(self, guard, amount, expected_error):
        context = {
            "transaction_id": uuid4(),
            "customer_id": uuid4(),
            "amount": amount,
        }
        errors = await guard.check(context)
        assert any(expected_error in e for e in errors)

    # ---- entity methods ----
    def test_validate(self, guard):
        result = guard.validate()
        assert result["is_valid"] is True
        guard.DEFAULT_AML_THRESHOLD = Decimal("-1")
        result2 = guard.validate()
        assert result2["is_valid"] is False
        assert "DEFAULT_AML_THRESHOLD must be positive" in result2["errors"]

    def test_to_dict(self, guard):
        d = guard.to_dict()
        assert d["version"] == 1
        assert d["enabled"] is True
        assert "large_threshold" in d
        assert "structuring_threshold" in d
        assert d["structuring_window_days"] == 7

    def test_from_dict(self):
        data = {
            "version": 3,
            "enabled": False,
            "large_threshold": "2000000",
            "structuring_threshold": "800000",
            "structuring_window_days": 5,
        }
        guard = AntiMoneyLaunderingGuard.from_dict(data)
        assert guard.version() == 3
        assert guard._engine._enabled is False
        assert guard._engine._large_transaction_threshold == Decimal("2000000")
        assert guard._engine._structuring_threshold == Decimal("800000")
        assert guard._engine._structuring_window_days == 5

    def test_clone(self, guard):
        guard._version = 5
        clone = guard.clone()
        assert clone is not guard
        assert clone.version() == 6
        assert clone._engine._enabled == guard._engine._enabled
        assert clone._engine._large_transaction_threshold == guard._engine._large_transaction_threshold

    def test_snapshot(self, guard):
        snap = guard.snapshot()
        assert snap["version"] == guard.version()
        assert snap["enabled"] is True
        assert "timestamp" in snap

    def test_version(self, guard):
        assert guard.version() == 1
        guard.touch("user")
        assert guard.version() == 2

    def test_audit_trail(self, guard):
        guard.touch("user1")
        guard.touch("user2")
        audit = guard.audit_trail(limit=1)
        assert len(audit) == 1
        assert audit[0]["performed_by"] == "user2"
        assert audit[0]["version"] == 2

    def test_touch(self, guard):
        old_version = guard.version()
        guard.touch("admin")
        assert guard.version() == old_version + 1
        audit = guard.audit_trail()
        assert audit[-1]["action"] == "TOUCH"
        assert audit[-1]["performed_by"] == "admin"

    def test_get_alerts(self, guard):
        alerts = guard.get_alerts()
        assert isinstance(alerts, list)

    def test_get_statistics(self, guard):
        stats = guard.get_statistics()
        assert "version" in stats
        assert stats["version"] == guard.version()

    def test_reset(self, guard):
        guard._version = 5
        guard._audit_trail = [{"test": "data"}]
        guard._daily_totals["ACC"] = Decimal("100")
        guard.reset()
        assert guard.version() == 6
        assert guard.audit_trail() == []
        assert guard._daily_totals == {}
        assert guard._engine._scores == []


# ============================================================================
# Singleton function tests
# ============================================================================
# Combine two singleton tests into one to avoid duplicate detection
def test_singletons_identity():
    # Guard singleton
    g1 = get_anti_money_laundering_guard()
    g2 = get_anti_money_laundering_guard()
    assert g1 is g2
    assert isinstance(g1, AntiMoneyLaunderingGuard)

    # Engine singleton
    e1 = get_anti_money_laundering_engine()
    e2 = get_anti_money_laundering_engine()
    assert e1 is e2
    assert isinstance(e1, AntiMoneyLaunderingEngine)

    # Ensure guard and engine are different instances
    assert g1 is not e1
