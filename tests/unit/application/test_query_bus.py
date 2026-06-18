#!/usr/bin/env python3
"""
Unit: Query Bus (CQRS)
Menguji query bus untuk read-side operations.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from types import SimpleNamespace

import pytest

from application.commands_cqrs.query_bus_unified import QueryBus


@dataclass(kw_only=True)
class GetJournalQuery:
    journal_id: str

    class GetJournalHandler:
        def handle(self, query: GetJournalQuery):
            # Return a simple object with the required attributes
            return SimpleNamespace(
                journal_id=query.journal_id, status="POSTED", amount=Decimal("1000000")
            )

            def test_query_bus_dispatch():
                bus = QueryBus()
                handler = GetJournalHandler()
                bus.register_handler(GetJournalQuery, handler)
                response = bus.dispatch(GetJournalQuery(journal_id="JRN-001"))
                assert response.journal_id == "JRN-001"
                assert response.status == "POSTED"

                def test_query_bus_raises_for_unregistered():
                    bus = QueryBus()
                    with pytest.raises(KeyError, match="No handler registered"):
                        bus.dispatch(GetJournalQuery(journal_id="xxx"))

                        def test_query_bus_with_middleware():
                            bus = QueryBus()

                            def log_middleware(query, handler):
                                print(f"Executing query: {query}")
                                return handler.handle(query)

                                bus.add_middleware(log_middleware)
                                handler = GetJournalHandler()
                                bus.register_handler(GetJournalQuery, handler)
                                response = bus.dispatch(GetJournalQuery(journal_id="JRN-002"))
                                assert response is not None
                                assert response.journal_id == "JRN-002"

                                if __name__ == "__main__":
                                    pytest.main([__file__])
