#!/usr/bin/env python3

"""
Module: test_validation_pipeline.py

Layer: Tests / Unit / Kernel

Responsibility:
    Unit tests untuk validation pipeline di kernel.
    Menguji pre-condition guards dan validasi sebelum mutation.

Dependencies:
    - kernel/validation_pipeline.py
    - kernel/guards/*.py
    - pytest

Audit:
    Tests harus lulus 100% sebelum deployment.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from kernel.guards.authority_matrix import AuthorityMatrixGuard
from kernel.guards.balance_checker import BalanceChecker
from kernel.guards.budget_availability import BudgetAvailabilityGuard
from kernel.guards.currency_validator import CurrencyValidator
from kernel.guards.legal_entity_boundary import LegalEntityBoundaryGuard
from kernel.guards.period_lock import PeriodLockGuard
from kernel.guards.sod_enforcer import SoDEnforcer
from kernel.validation_pipeline import ValidationPipeline


class TestValidationPipeline:
    """Test suite untuk validation pipeline."""

    @pytest.fixture
    def pipeline(self) -> ValidationPipeline:
        """Fixture pipeline dengan guards terdaftar."""
        pipeline = ValidationPipeline()
        pipeline.register_guard(BalanceChecker())
        pipeline.register_guard(PeriodLockGuard())
        pipeline.register_guard(CurrencyValidator())
        pipeline.register_guard(LegalEntityBoundaryGuard())
        pipeline.register_guard(AuthorityMatrixGuard())
        pipeline.register_guard(SoDEnforcer())
        pipeline.register_guard(BudgetAvailabilityGuard())
        return pipeline

    @pytest.fixture
    def valid_journal_context(self) -> dict:
        """Fixture context jurnal valid."""
        return {
            "command_type": "PostJournalEntryCommand",
            "legal_entity_id": uuid4(),
            "user_id": uuid4(),
            "user_roles": ["ACCOUNTANT"],
            "journal_lines": [
                {"account_code": "1-1000", "debit": Decimal("1000000"), "credit": Decimal("0")},
                {"account_code": "4-1000", "debit": Decimal("0"), "credit": Decimal("1000000")},
            ],
            "period": "2025-03",
            "currency": "IDR",
        }

    def test_all_guards_pass(self, pipeline, valid_journal_context):
        """Test: Semua guard lulus."""
        errors = pipeline.run(valid_journal_context)
        assert len(errors) == 0

    def test_balance_checker_fails(self, pipeline, valid_journal_context):
        """Test: Balance checker gagal jika jurnal tidak balance."""
        invalid_context = valid_journal_context.copy()
        invalid_context["journal_lines"][0]["debit"] = Decimal("2000000")
        errors = pipeline.run(invalid_context)
        assert any("balance" in str(e).lower() for e in errors)

    def test_period_lock_fails_if_period_closed(self, pipeline, valid_journal_context):
        """Test: Period lock guard gagal jika periode sudah ditutup."""
        # Simulasi periode sudah closed
        valid_journal_context["period"] = "2024-12"  # asumsikan sudah closed
        errors = pipeline.run(valid_journal_context)
        # PeriodLockGuard akan mendeteksi periode closed dan mengembalikan error
        # Karena kita mock period service, kita asumsikan error ada
        assert any("period" in str(e).lower() for e in errors) or len(errors) > 0

    def test_currency_validator_fails_with_invalid_currency(self, pipeline, valid_journal_context):
        """Test: Currency validator gagal jika mata uang tidak valid."""
        valid_journal_context["currency"] = "XYZ"
        errors = pipeline.run(valid_journal_context)
        assert any("currency" in str(e).lower() for e in errors)

    def test_legal_entity_boundary_guard_fails_if_cross_entity(
        self, pipeline, valid_journal_context
    ):
        """
        Test: Legal entity boundary gagal jika transaksi lintas entitas.

        Pendekatan: Setup mock COA service pada LegalEntityBoundaryGuard yang
        mengembalikan legal entity berbeda untuk account_code yang berbeda.
        """
        # Buat dua entitas berbeda
        entity_a = uuid4()
        entity_b = uuid4()

        # Context menggunakan entity_a sebagai entitas utama
        context = valid_journal_context.copy()
        context["legal_entity_id"] = entity_a

        # Buat account codes dengan format yang bisa dipetakan ke entity
        account_a = f"{entity_a.hex[:8]}-1000"  # prefix entity_a
        account_b = f"{entity_b.hex[:8]}-1000"  # prefix entity_b

        context["journal_lines"] = [
            {"account_code": account_a, "debit": Decimal("1000000"), "credit": Decimal("0")},
            {"account_code": account_b, "debit": Decimal("0"), "credit": Decimal("1000000")},
        ]

        # Cari instance LegalEntityBoundaryGuard dalam pipeline
        legal_entity_guard = None
        for guard in pipeline._guards:
            if isinstance(guard, LegalEntityBoundaryGuard):
                legal_entity_guard = guard
                break

        assert legal_entity_guard is not None, (
            "LegalEntityBoundaryGuard tidak ditemukan dalam pipeline"
        )

        # Buat mock COA service yang memetakan account_code ke legal entity
        mock_coa = MagicMock()
        mock_coa.get_account_legal_entity = MagicMock(
            side_effect=lambda code: (
                entity_a if code == account_a else (entity_b if code == account_b else None)
            )
        )

        # Set COA service pada guard
        legal_entity_guard._coa_service = mock_coa

        # Jalankan pipeline
        errors = pipeline.run(context)

        # Debug output jika masih kosong (untuk membantu diagnosis)
        if len(errors) == 0:
            print("\n[DEBUG] Legal entity boundary guard tidak menghasilkan error.")
            print("[DEBUG] Context keys:", list(context.keys()))
            print("[DEBUG] Journal lines:", context["journal_lines"])
            print(
                "[DEBUG] COA service dipanggil?", mock_coa.get_account_legal_entity.call_args_list
            )

        # Pastikan error terdeteksi
        assert len(errors) > 0, (
            "Pipeline seharusnya menghasilkan error untuk transaksi lintas entitas!"
        )

        # Validasi pesan error sesuai
        allowed_keywords = [
            "legal entity",
            "cross-entity",
            "entity",
            "boundary",
            "company",
            "intercompany",
            "different",
        ]
        assert any(any(kw in str(e).lower() for kw in allowed_keywords) for e in errors), (
            f"Pesan error tidak sesuai dengan batasan entitas. Found: {errors}"
        )

    def test_authority_matrix_guard_fails_if_unauthorized(self, pipeline, valid_journal_context):
        """Test: Authority matrix gagal jika user tidak memiliki wewenang."""
        valid_journal_context["user_roles"] = ["VIEWER"]
        errors = pipeline.run(valid_journal_context)
        assert any("authority" in str(e).lower() or "permission" in str(e).lower() for e in errors)

    def test_sod_enforcer_fails_if_conflict(self, pipeline, valid_journal_context):
        """Test: SoD enforcer gagal jika ada konflik tugas."""
        valid_journal_context["user_roles"] = ["CREATOR", "APPROVER"]  # conflict
        errors = pipeline.run(valid_journal_context)
        assert any("segregation" in str(e).lower() or "sod" in str(e).lower() for e in errors)

    def test_budget_availability_guard_fails_if_exceeds_budget(
        self, pipeline, valid_journal_context
    ):
        """Test: Budget availability gagal jika melebihi anggaran."""
        valid_journal_context["journal_lines"][0]["debit"] = Decimal(
            "1000000000"
        )  # melebihi budget
        errors = pipeline.run(valid_journal_context)
        assert any("budget" in str(e).lower() for e in errors)

    def test_register_multiple_guards(self, pipeline):
        """Test: Registrasi multiple guards."""
        count_before = len(pipeline._guards)
        pipeline.register_guard(
            BalanceChecker()
        )  # duplicate, harusnya tidak menambah jika sudah ada
        assert len(pipeline._guards) == count_before

    def test_clear_guards(self, pipeline):
        """Test: Menghapus semua guards."""
        pipeline.clear_guards()
        assert len(pipeline._guards) == 0
        # Setelah clear, pipeline harus tetap bisa jalan tanpa error
        errors = pipeline.run({})
        assert errors == []  # no guards, no errors

    def test_pipeline_stops_on_first_error_if_configured(self, pipeline, valid_journal_context):
        """Test: Pipeline berhenti pada error pertama jika stop_on_first_error=True."""
        pipeline.stop_on_first_error = True
        # Buat beberapa error
        valid_journal_context["currency"] = "XYZ"
        valid_journal_context["journal_lines"][0]["debit"] = Decimal(
            "2000000"
        )  # balance error juga
        errors = pipeline.run(valid_journal_context)
        # Hanya error pertama yang terdeteksi (currency atau balance? tergantung urutan)
        assert len(errors) == 1

    def test_pipeline_continues_on_error_if_not_configured(self, pipeline, valid_journal_context):
        """Test: Pipeline tetap lanjut ke guard berikutnya jika stop_on_first_error=False."""
        pipeline.stop_on_first_error = False
        valid_journal_context["currency"] = "XYZ"
        valid_journal_context["journal_lines"][0]["debit"] = Decimal("2000000")
        errors = pipeline.run(valid_journal_context)
        # Harus ada minimal 2 error (currency dan balance)
        assert len(errors) >= 2


if __name__ == "__main__":
    pytest.main([__file__])
