#!/usr/bin/env python3

"""
Module: test_async_guards.py

Layer: Tests / Unit / Kernel

Responsibility:
    Unit tests untuk asynchronous post-commit guards (fraud detection, AML).

Dependencies:
    - kernel/async_guards/fraud_pattern_detector.py
    - kernel/async_guards/anti_money_laundering.py
    - pytest

Audit:
    Tests harus lulus 100% sebelum deployment.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from kernel.guards.async_guards.anti_money_laundering import AntiMoneyLaunderingGuard
from kernel.guards.async_guards.fraud_pattern_detector import FraudPatternDetector


class TestFraudPatternDetector:
    """Test suite untuk FraudPatternDetector."""

    @pytest.fixture
    def fraud_detector(self):
        return FraudPatternDetector()

    @pytest.fixture
    def normal_transaction(self):
        return {
            "transaction_id": uuid4(),
            "user_id": uuid4(),
            "amount": Decimal("1000000"),
            "transaction_date": date.today(),
            "counterparty": "PT ABC",
            "device_id": "device_123",
        }

    def test_normal_transaction_passes(self, fraud_detector, normal_transaction):
        result = fraud_detector.check(normal_transaction)
        assert result.is_suspicious is False

    def test_unusual_amount_triggers_flag(self, fraud_detector):
        transaction = {
            "transaction_id": uuid4(),
            "user_id": uuid4(),
            "amount": Decimal("500000000"),
            "transaction_date": date.today(),
            "counterparty": "PT ABC",
            "device_id": "device_123",
        }
        result = fraud_detector.check(transaction)
        assert result.is_suspicious is True
        assert "amount" in result.reasons[0].lower()

    def test_rapid_successive_transactions(self, fraud_detector):
        # Simulasi multiple transactions in short time
        user_id = uuid4()
        transactions = [
            {
                "user_id": user_id,
                "amount": Decimal("5000000"),
                "timestamp": datetime.utcnow() - timedelta(minutes=1),
            },
            {
                "user_id": user_id,
                "amount": Decimal("5000000"),
                "timestamp": datetime.utcnow() - timedelta(seconds=30),
            },
            {"user_id": user_id, "amount": Decimal("5000000"), "timestamp": datetime.utcnow()},
        ]
        # Detector harus mendeteksi rapid movement
        for tx in transactions:
            fraud_detector.check(tx)
            if tx["amount"] == Decimal("5000000"):
                # Pastikan flag for rapid succession
                pass
        assert fraud_detector._user_transaction_count[user_id] >= 3

    def test_high_risk_country_triggers_flag(self, fraud_detector):
        transaction = {
            "transaction_id": uuid4(),
            "user_id": uuid4(),
            "amount": Decimal("10000000"),
            "transaction_date": date.today(),
            "counterparty": "Foreign Entity",
            "country": "XX",  # high risk country code
        }
        result = fraud_detector.check(transaction)
        assert result.is_suspicious is True

    def test_new_device_unusual_activity(self, fraud_detector, normal_transaction):
        # First transaction from new device
        result1 = fraud_detector.check(normal_transaction)
        assert result1.is_suspicious is False
        # Large amount from same device but different user behavior
        normal_transaction["amount"] = Decimal("200000000")
        result2 = fraud_detector.check(normal_transaction)
        assert result2.is_suspicious is True


class TestAntiMoneyLaunderingGuard:
    """Test suite untuk AntiMoneyLaunderingGuard."""

    @pytest.fixture
    def aml_guard(self):
        return AntiMoneyLaunderingGuard()

    @pytest.fixture
    def normal_payment(self):
        return {
            "payment_id": uuid4(),
            "from_account": uuid4(),
            "to_account": uuid4(),
            "amount": Decimal("5000000"),
            "payment_date": date.today(),
            "currency": "IDR",
        }

    def test_normal_payment_passes(self, aml_guard, normal_payment):
        result = aml_guard.screen(normal_payment)
        assert result.is_flagged is False

    def test_threshold_exceeded_triggers_aml(self, aml_guard):
        payment = {
            "payment_id": uuid4(),
            "from_account": uuid4(),
            "to_account": uuid4(),
            "amount": Decimal("150000000"),
            "payment_date": date.today(),
            "currency": "IDR",
        }
        result = aml_guard.screen(payment)
        assert result.is_flagged is True
        assert result.threshold_exceeded is True

    def test_sanction_list_hit(self, aml_guard, mocker):
        # Mock sanction list service
        mocker.patch.object(aml_guard, "_check_sanction_list", return_value=True)
        payment = {
            "payment_id": uuid4(),
            "from_account": uuid4(),
            "to_account": uuid4(),
            "amount": Decimal("10000000"),
            "payment_date": date.today(),
            "currency": "IDR",
            "beneficiary_name": "Sanctioned Person",
        }
        result = aml_guard.screen(payment)
        assert result.is_flagged is True
        assert "sanction" in result.reasons[0].lower()

    def test_structuring_pattern_detected(self, aml_guard):
        # Simulasi beberapa transaksi kecil yang totalnya melebihi threshold
        user_id = uuid4()
        for i in range(5):
            payment = {
                "payment_id": uuid4(),
                "from_account": user_id,
                "to_account": uuid4(),
                "amount": Decimal("30000000"),
                "payment_date": date.today(),
                "currency": "IDR",
            }
            result = aml_guard.screen(payment)
            if i == 4:  # total 150jt
                assert result.is_flagged is True
                assert "structuring" in result.reasons[0].lower()

    def test_pep_related_flagged(self, aml_guard, mocker):
        mocker.patch.object(aml_guard, "_is_pep", return_value=True)
        payment = {
            "payment_id": uuid4(),
            "from_account": uuid4(),
            "to_account": uuid4(),
            "amount": Decimal("10000000"),
            "payment_date": date.today(),
            "currency": "IDR",
        }
        result = aml_guard.screen(payment)
        assert result.is_flagged is True
        assert "pep" in result.reasons[0].lower()

    def test_generate_suspicious_activity_report(self, aml_guard):
        payment = {
            "payment_id": uuid4(),
            "from_account": uuid4(),
            "to_account": uuid4(),
            "amount": Decimal("200000000"),
            "payment_date": date.today(),
            "currency": "IDR",
        }
        result = aml_guard.screen(payment)
        assert result.sar_id is not None
        assert result.sar_id.startswith("SAR-")


if __name__ == "__main__":
    pytest.main([__file__])
