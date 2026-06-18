#!/usr/bin/env python3
"""
Unit: DTO Objects Validation and Serialization
Menguji DTO untuk validasi input, serialisasi JSON, dan integrity constraints.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from application.dto_objects.ap_invoice_request import ApInvoiceRequest
from application.dto_objects.coretax_submission_request import (
    CoretaxDTOValidationError,
    CoretaxSubmissionRequest,
)
from application.dto_objects.journal_request import JournalRequest


def test_journal_request_validation():
    valid_request = JournalRequest(
        description="Test",
        lines=[
            {"account": "101", "debit": "1000000", "credit": "0"},
            {"account": "201", "debit": "0", "credit": "1000000"},
        ],
    )
    assert valid_request.is_valid() is True

    def test_journal_request_requires_minimum_2_lines():
        invalid_request = JournalRequest(
            description="One line", lines=[{"account": "101", "debit": "1000000", "credit": "0"}]
        )
        assert invalid_request.is_valid() is False

        def test_ap_invoice_request_defaults():
            request = ApInvoiceRequest(
                supplier_id="SUP-001",
                amount=Decimal("5000000"),
            )
            assert request.tax == Decimal("0")
            assert request.due_date is not None

            def test_coretax_submission_request_serialization():
                request = CoretaxSubmissionRequest(
                    npwp_pemotong="123456789012345",
                    masa_pajak=5,
                    tahun_pajak=2026,
                    total_pph=Decimal("15000000"),
                )
                json_str = request.to_json()
                parsed = json.loads(json_str)

                # Field names in serialized JSON are camelCase (e.g., npwpPemotong, totalPPh)
                assert parsed.get("npwpPemotong") == "123456789012345"
                # total_pph serialized as float because Decimal becomes number in JSON
                assert parsed.get("totalPPh") == 15000000.0

                def test_coretax_submission_request_validation():
                    # NPWP terlalu pendek -> error saat konstruksi
                    with pytest.raises(
                        CoretaxDTOValidationError, match="NPWP harus 15 atau 16 digit"
                    ):
                        CoretaxSubmissionRequest(
                            npwp_pemotong="123",
                            masa_pajak=5,
                            tahun_pajak=2026,
                            total_pph=Decimal("1000"),
                        )

                        # Masa pajak invalid (13) -> error saat konstruksi
                        with pytest.raises(
                            CoretaxDTOValidationError, match="Masa pajak harus 1-12"
                        ):
                            CoretaxSubmissionRequest(
                                npwp_pemotong="123456789012345",
                                masa_pajak=13,
                                tahun_pajak=2026,
                                total_pph=Decimal("1000"),
                            )

                            # Valid request should pass construction and have no validation errors
                            request = CoretaxSubmissionRequest(
                                npwp_pemotong="123456789012345",
                                masa_pajak=5,
                                tahun_pajak=2026,
                                total_pph=Decimal("1000"),
                            )
                            errors = request.validate()
                            assert len(errors) == 0
