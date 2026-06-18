#!/usr/bin/env python3
"""Unit test untuk immutable event writer."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from audit.event_writer_immutable import (
    ImmutableEventWriter,
    InvalidEventTypeError,
    MissingRequiredFieldError,
)


class DuplicateKeyError(Exception):
    """Dummy exception untuk mensimulasikan error duplikasi dari store."""

    pass

    class TestImmutableEventWriter:
        @pytest.fixture
        async def writer(self):
            """Fixture yang menyediakan ImmutableEventWriter dengan semua dependensi di-mock."""
            # Reset singleton
            import audit.event_writer_immutable as module

            module._immutable_event_writer = None

            # Patch semua fungsi dari event_types_catalog yang digunakan
            with (
                patch(
                    "audit.event_types_catalog.EventTypeCatalog.is_valid_type", return_value=True
                ),
                patch(
                    "audit.event_types_catalog.EventTypeCatalog.get_default_severity",
                    return_value="INFO",
                ),
                patch(
                    "audit.event_types_catalog.EventMetadataSchema.get_schema",
                    return_value={"required_fields": []},
                ),
                patch(
                    "audit.event_writer_immutable.get_current_correlation_id",
                    return_value="test-correlation",
                ),
            ):
                writer_instance = ImmutableEventWriter()

                # Mock store langsung agar tidak perlu async init
                mock_store = AsyncMock()
                mock_store.append = AsyncMock(return_value=uuid.uuid4())
                mock_store.get_last_event = AsyncMock(return_value=None)
                writer_instance._store = mock_store
                writer_instance._hash_builder = MagicMock()
                writer_instance._hash_builder.get_last_hash = AsyncMock(return_value="genesis")
                yield writer_instance

                @pytest.mark.asyncio
                async def test_write_event_assigns_id_and_hash(self, writer):
                    """Test bahwa write_event menambahkan id, hash, dan timestamp."""
                    event_type = "test.event"
                    original_data = {"key": "value"}

                    event_id = await writer.write_event(event_type, original_data)

                    assert event_id is not None
                    writer._store.append.assert_called_once()
                    call_args = writer._store.append.call_args
                    event_data = call_args.kwargs.get("event_data")
                    assert event_data is not None
                    assert "id" in event_data
                    assert "hash" in event_data
                    assert "timestamp" in event_data
                    assert event_data["event_type"] == event_type
                    # Check original data fields are present (enriched, not equal)
                    for k, v in original_data.items():
                        assert event_data["data"][k] == v
                        # Check metadata added
                        assert "correlation_id" in event_data["data"]
                        assert "timestamp" in event_data["data"]

                        @pytest.mark.asyncio
                        async def test_cannot_overwrite_existing_event(self, writer):
                            """Test bahwa write_event menolak event dengan ID yang sudah ada (simulasi dari store)."""
                            writer._store.append = AsyncMock(
                                side_effect=DuplicateKeyError("Event already exists")
                            )

                            with pytest.raises(DuplicateKeyError, match="already exists"):
                                await writer.write_event("test.event", {"id": str(uuid4())})

                                @pytest.mark.asyncio
                                async def test_invalid_event_type_raises_error(self, writer):
                                    """Test bahwa event type tidak valid memicu InvalidEventTypeError."""
                                    with patch(
                                        "audit.event_types_catalog.EventTypeCatalog.is_valid_type",
                                        return_value=False,
                                    ):
                                        with pytest.raises(
                                            InvalidEventTypeError, match="Invalid event type"
                                        ):
                                            await writer.write_event("invalid.type", {})

                                            @pytest.mark.asyncio
                                            async def test_missing_required_fields_raises_error(
                                                self, writer
                                            ):
                                                """Test bahwa field required yang hilang memicu MissingRequiredFieldError."""
                                                with (
                                                    patch(
                                                        "audit.event_types_catalog.EventMetadataSchema.get_schema",
                                                        return_value={
                                                            "required_fields": ["required_field"]
                                                        },
                                                    ),
                                                    pytest.raises(
                                                        MissingRequiredFieldError,
                                                        match="Missing required fields",
                                                    ),
                                                ):
                                                    await writer.write_event("test.event", {})

                                                    if __name__ == "__main__":
                                                        pytest.main([__file__])
