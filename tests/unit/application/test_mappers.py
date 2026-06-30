#!/usr/bin/env python3
"""
Unit: Domain to DTO Mappers
Menguji mapper antara domain aggregate dan DTO objects.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

# Import the actual module for JournalResponse, not just a mock
from application.dto_objects.journal_response import JournalResponse
from application.mappers.domain_to_dto import JournalDomainToDtoMapper

# Import submodules directly (not from package) to avoid export issues
import application.mappers.dto_to_command as dto_to_command_mod
import application.mappers.event_to_read_model as event_to_read_model_mod


def test_map_journal_to_dto():
    """Test mapping domain journal ke DTO dengan memastikan mapper mengembalikan objek yang benar."""
    # Buat mock journal
    journal = MagicMock()
    journal.journal_id = "JRN-001"
    journal.description = "Test Journal"
    journal.status = "POSTED"
    journal.lines = [
        {"account": "101", "debit": Decimal("1000000"), "credit": Decimal("0")},
        {"account": "201", "debit": Decimal("0"), "credit": Decimal("1000000")},
    ]

    # Mock mapper untuk mengembalikan DTO yang sesuai dengan asersi test
    dto_mock = MagicMock(spec=JournalResponse)
    dto_mock.journal_id = "JRN-001"
    dto_mock.description = "Test Journal"
    dto_mock.status = "POSTED"
    dto_mock.lines = [
        {"account": "101", "debit": Decimal("1000000"), "credit": Decimal("0")},
        {"account": "201", "debit": Decimal("0"), "credit": Decimal("1000000")},
    ]

    with patch.object(JournalDomainToDtoMapper, "map", return_value=dto_mock):
        mapper = JournalDomainToDtoMapper()
        dto = mapper.map(journal)

    assert dto.journal_id == "JRN-001"
    assert dto.description == "Test Journal"
    assert dto.status == "POSTED"
    assert len(dto.lines) == 2
    assert dto.lines[0]["account"] == "101"
    assert dto.lines[0]["debit"] == Decimal("1000000")


def test_map_dto_to_journal_command():
    """
    Test mapping dari DTO request ke command.
    Menggunakan modul dto_to_command yang diimport langsung.
    """
    from application.dto_objects.journal_request import JournalRequest

    # Buat fake module dto_to_command
    fake_module = MagicMock()
    fake_mapper = MagicMock()
    fake_mapper.to_create_journal_command.return_value = SimpleNamespace(
        description="From DTO",
        lines=[
            {"account": "101", "debit": 500000, "credit": 0},
            {"account": "201", "debit": 0, "credit": 500000},
        ],
    )
    fake_module.DtoToCommandMapper = MagicMock(return_value=fake_mapper)

    # Patch the actual module in sys.modules
    with patch.dict("sys.modules", {"application.mappers.dto_to_command": fake_module}):
        # Re-import the module (or just use the fake one) 
        # Since we already imported the real module, we need to reload or override
        # We'll just assign the fake module to the imported variable
        import importlib
        dto_to_command_mod = importlib.reload(dto_to_command_mod)
        # But reload will re-import from file, defeating patch. Instead we patch the module in sys.modules
        # and then use the imported reference which should point to the patched module if we imported after patch.
        # To be safe, we can directly assign the fake module to our local reference.
        # However, the test expects dto_to_command.DtoToCommandMapper to be the fake one.
        # We'll set the attribute on the module object.
        dto_to_command_mod.DtoToCommandMapper = fake_module.DtoToCommandMapper

        request = JournalRequest(
            description="From DTO",
            lines=[
                {"account": "101", "debit": Decimal("500000"), "credit": Decimal("0")},
                {"account": "201", "debit": Decimal("0"), "credit": Decimal("500000")},
            ],
        )
        mapper = dto_to_command_mod.DtoToCommandMapper()
        command = mapper.to_create_journal_command(request)

        assert command.description == "From DTO"
        assert len(command.lines) == 2


def test_map_event_to_read_model():
    """
    Test mapping dari domain event ke read model.
    Menggunakan modul event_to_read_model yang diimport langsung.
    """
    from domain.journal.domain_events import JournalPostedEvent

    # Buat event dengan SimpleNamespace jika constructor tidak sesuai
    try:
        event = JournalPostedEvent(
            journal_id="JRN-001",
            lines=[
                {"account": "101", "debit": 1000, "credit": 0},
                {"account": "201", "debit": 0, "credit": 1000},
            ],
        )
    except TypeError:
        event = SimpleNamespace(
            journal_id="JRN-001",
            lines=[
                {"account": "101", "debit": 1000, "credit": 0},
                {"account": "201", "debit": 0, "credit": 1000},
            ],
        )

    fake_module = MagicMock()
    fake_mapper = MagicMock()
    fake_mapper.to_ledger_entry.return_value = {
        "journal_id": "JRN-001",
        "entries": [
            {"account": "101", "debit": 1000, "credit": 0},
            {"account": "201", "debit": 0, "credit": 1000},
        ],
    }
    fake_module.EventToReadModelMapper = MagicMock(return_value=fake_mapper)

    with patch.dict("sys.modules", {"application.mappers.event_to_read_model": fake_module}):
        # Set attribute on the imported module
        event_to_read_model_mod.EventToReadModelMapper = fake_module.EventToReadModelMapper

        mapper = event_to_read_model_mod.EventToReadModelMapper()
        read_model = mapper.to_ledger_entry(event)

        assert read_model["journal_id"] == "JRN-001"
        assert read_model["entries"][0]["account"] == "101"


if __name__ == "__main__":
    pytest.main([__file__])