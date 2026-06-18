#!/usr/bin/env python3
"""Unit test untuk Bank MT940 parser adapter."""

from __future__ import annotations

from decimal import Decimal

import pytest

from adapters.secondary_impl.bank_mt940_parser_adapter import BankMT940Parser


class TestBankMT940Parser:
    def test_parse_valid_mt940(self):
        content = """\
        :20:STARTUM
        :25:123456789
        :28:1
        :60F:C250101IDR100000000,
        :61:2501020102D1000000NTRF//Bank fee
        :62F:C250103IDR99000000,
        """
        parser = BankMT940Parser()
        transactions = parser.parse(content)
        assert len(transactions) == 1
        assert transactions[0]["amount"] == Decimal("-1000000")
        assert transactions[0]["description"] == "Bank fee"

        def test_parse_invalid_format_raises(self):
            parser = BankMT940Parser()
            with pytest.raises(ValueError, match="Invalid MT940"):
                parser.parse("invalid content")
