# tests/infrastructure/caching/test_serialization_json.py
# Perbaikan kualitas assertions: menghapus semua assert True,
# diganti dengan assertion yang memeriksa nilai aktual, roundtrip, efek samping, dll.

import base64
import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from infrastructure.caching.serialization_json import (
    COMPRESSED_PREFIX,
    COMPRESSION_AVAILABLE,
    CacheSchema,
    CustomJSONDecoder,
    CustomJSONEncoder,
    IdempotencyManager,
    JSONSerializer,
    deserialize,
    deserialize_from_string,
    get_json_serializer,
    serialize,
    serialize_to_string,
)


# ============================================================================
# CustomJSONEncoder tests
# ============================================================================
class TestCustomJSONEncoder:
    def test_encode_datetime(self):
        dt = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        encoded = json.dumps(dt, cls=CustomJSONEncoder)
        expected = '{"__type__": "datetime", "value": "2024-01-01T12:00:00+00:00"}'
        assert encoded == expected

    def test_encode_date(self):
        d = date(2024, 1, 1)
        encoded = json.dumps(d, cls=CustomJSONEncoder)
        expected = '{"__type__": "date", "value": "2024-01-01"}'
        assert encoded == expected

    def test_encode_uuid(self):
        import uuid
        u = uuid.UUID("12345678123456781234567812345678")
        encoded = json.dumps(u, cls=CustomJSONEncoder)
        expected = '{"__type__": "uuid", "value": "12345678-1234-5678-1234-567812345678"}'
        assert encoded == expected

    def test_encode_decimal(self):
        d = Decimal("10.50")
        encoded = json.dumps(d, cls=CustomJSONEncoder)
        expected = '{"__type__": "decimal", "value": "10.50"}'
        assert encoded == expected

    def test_encode_bytes(self):
        b = b"hello"
        encoded = json.dumps(b, cls=CustomJSONEncoder)
        b64 = base64.b64encode(b).decode("ascii")
        expected = f'{{"__type__": "bytes", "value": "{b64}"}}'
        assert encoded == expected

    def test_encode_set(self):
        s = {1, 2, 3}
        encoded = json.dumps(s, cls=CustomJSONEncoder)
        # set order not guaranteed, so parse and compare
        decoded = json.loads(encoded)
        assert decoded["__type__"] == "set"
        assert set(decoded["value"]) == {1, 2, 3}

    def test_encode_fallback(self):
        # Fallback to default for unsupported type
        class Unsupported:
            pass
        obj = Unsupported()
        with pytest.raises(TypeError):
            json.dumps(obj, cls=CustomJSONEncoder)


# ============================================================================
# CustomJSONDecoder tests
# ============================================================================
class TestCustomJSONDecoder:
    def test_decode_datetime(self):
        data = '{"__type__": "datetime", "value": "2024-01-01T12:00:00+00:00"}'
        decoded = json.loads(data, cls=CustomJSONDecoder)
        assert isinstance(decoded, datetime)
        assert decoded == datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)

    def test_decode_date(self):
        data = '{"__type__": "date", "value": "2024-01-01"}'
        decoded = json.loads(data, cls=CustomJSONDecoder)
        assert isinstance(decoded, date)
        assert decoded == date(2024, 1, 1)

    def test_decode_uuid(self):
        import uuid
        data = '{"__type__": "uuid", "value": "12345678-1234-5678-1234-567812345678"}'
        decoded = json.loads(data, cls=CustomJSONDecoder)
        assert isinstance(decoded, uuid.UUID)
        assert decoded == uuid.UUID("12345678-1234-5678-1234-567812345678")

    def test_decode_decimal(self):
        data = '{"__type__": "decimal", "value": "10.50"}'
        decoded = json.loads(data, cls=CustomJSONDecoder)
        assert isinstance(decoded, Decimal)
        assert decoded == Decimal("10.50")

    def test_decode_bytes(self):
        b64 = base64.b64encode(b"hello").decode("ascii")
        data = f'{{"__type__": "bytes", "value": "{b64}"}}'
        decoded = json.loads(data, cls=CustomJSONDecoder)
        assert decoded == b"hello"

    def test_decode_set(self):
        data = '{"__type__": "set", "value": [1, 2, 3]}'
        decoded = json.loads(data, cls=CustomJSONDecoder)
        assert decoded == {1, 2, 3}

    def test_decode_unknown_type(self):
        data = '{"__type__": "unknown", "value": "foo"}'
        decoded = json.loads(data, cls=CustomJSONDecoder)
        assert decoded == {"__type__": "unknown", "value": "foo"}

    def test_decode_normal_object(self):
        data = '{"foo": "bar"}'
        decoded = json.loads(data, cls=CustomJSONDecoder)
        assert decoded == {"foo": "bar"}


# ============================================================================
# IdempotencyManager tests
# ============================================================================
class TestIdempotencyManager:
    @pytest.fixture
    def manager(self):
        return IdempotencyManager()

    def test_cache_and_get(self, manager):
        key = "k1"
        method = "m1"
        result = {"status": "ok"}
        manager.cache_result(key, method, result)
        cached = manager.get_cached_result(key, method)
        assert cached == result

    def test_get_nonexistent(self, manager):
        assert manager.get_cached_result("k1", "m1") is None

    def test_ttl_expiry(self, manager):
        key = "k1"
        method = "m1"
        result = {"status": "ok"}
        manager.cache_result(key, method, result)
        # Manually set TTL to expired by patching timestamp
        storage_key = manager._get_key(key, method)
        # Simulate time travel: set timestamp to old
        old_time = datetime.now() - timedelta(seconds=manager._ttl_seconds + 10)
        manager._storage[storage_key] = (manager._storage[storage_key][0], old_time)
        cached = manager.get_cached_result(key, method)
        assert cached is None
        # Entry should be removed
        assert storage_key not in manager._storage

    def test_cache_result_invalid_json(self, manager):
        # Force invalid JSON by patching json.dumps to raise TypeError
        with patch("json.dumps", side_effect=TypeError("bad")):
            manager.cache_result("key", "method", {"x": MagicMock()})
        # Should store a fallback representation
        cached = manager.get_cached_result("key", "method")
        assert cached is not None
        assert "result" in cached  # fallback dict


# ============================================================================
# JSONSerializer tests
# ============================================================================
class TestJSONSerializer:
    @pytest.fixture
    def serializer(self):
        return JSONSerializer(use_compression=False)  # disable compression for basic tests

    def test_serialize_deserialize_roundtrip(self, serializer):
        data = {
            "int": 42,
            "float": 3.14,
            "str": "hello",
            "bool": True,
            "list": [1, 2, 3],
            "dict": {"a": 1},
            "dt": datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
            "date": date(2024, 1, 1),
            "uuid": UUID("12345678-1234-5678-1234-567812345678"),
            "decimal": Decimal("10.50"),
            "bytes": b"hello",
            "set": {1, 2, 3},
        }
        serialized = serializer.serialize(data)
        deserialized = serializer.deserialize(serialized)
        assert deserialized == data

    def test_serialize_version(self, serializer):
        data = {"a": 1}
        serialized = serializer.serialize(data, version=2)
        # deserialize should still work (version warning but returns data)
        deserialized = serializer.deserialize(serialized)
        assert deserialized == data

    def test_deserialize_none(self, serializer):
        assert serializer.deserialize(b"") is None
        assert serializer.deserialize(None) is None

    def test_deserialize_invalid_json(self, serializer):
        result = serializer.deserialize(b"invalid json")
        assert result is None

    def test_serialize_to_string(self, serializer):
        data = {"a": 1, "b": "hello"}
        s = serializer.serialize_to_string(data)
        # Check it's valid JSON
        parsed = json.loads(s)
        assert parsed == data

    def test_deserialize_from_string(self, serializer):
        s = '{"a": 1, "b": "hello"}'
        result = serializer.deserialize_from_string(s)
        assert result == {"a": 1, "b": "hello"}

    def test_deserialize_from_string_empty(self, serializer):
        assert serializer.deserialize_from_string("") is None

    def test_compression_enabled(self):
        # Test that compression works when enabled and data large
        # We need to mock compressor or use real if available
        if not COMPRESSION_AVAILABLE:
            pytest.skip("Compression not available")
        serializer = JSONSerializer(use_compression=True, compress_threshold=1)  # small threshold
        data = {"x": "a" * 2000}  # large data
        serialized = serializer.serialize(data)
        # Should be compressed
        assert serialized.startswith(COMPRESSED_PREFIX)
        deserialized = serializer.deserialize(serialized)
        assert deserialized == data

    def test_compression_disabled(self, serializer):
        # compression disabled by fixture (use_compression=False)
        data = {"x": "a" * 2000}
        serialized = serializer.serialize(data)
        assert not serialized.startswith(COMPRESSED_PREFIX)

    def test_serialize_fallback_encoder(self, serializer):
        # Ensure that default fallback works for non-serializable objects
        class Custom:
            pass
        obj = Custom()
        # Should raise TypeError because Custom is not serializable
        with pytest.raises(TypeError):
            serializer.serialize_to_string(obj)


# ============================================================================
# CacheSchema tests
# ============================================================================
class TestCacheSchema:
    def test_create_cache_entry_no_idempotency(self):
        entry = CacheSchema.create_cache_entry(data={"foo": "bar"}, ttl_seconds=60)
        assert entry["data"] == {"foo": "bar"}
        assert entry["ttl"] == 60
        assert "created_at" in entry
        assert "expires_at" in entry
        # expires_at should be approx now + 60
        now_ts = datetime.now(UTC).timestamp()
        assert entry["expires_at"] > now_ts + 55

    def test_create_cache_entry_with_idempotency(self):
        # First call should create new entry
        entry1 = CacheSchema.create_cache_entry(data={"foo": "bar"}, ttl_seconds=60, idempotency_key="key1")
        # Second call with same key should return cached entry
        entry2 = CacheSchema.create_cache_entry(data={"different": "data"}, ttl_seconds=60, idempotency_key="key1")
        assert entry1 == entry2
        # Different key should create new entry
        entry3 = CacheSchema.create_cache_entry(data={"foo": "bar"}, ttl_seconds=60, idempotency_key="key2")
        assert entry1 != entry3

    def test_validate_cache_entry_valid(self):
        entry = {
            "data": {},
            "created_at": datetime.now(UTC).isoformat(),
            "ttl": 60,
        }
        assert CacheSchema.validate_cache_entry(entry) is True

    def test_validate_cache_entry_invalid(self):
        # Missing fields
        entry = {"data": {}}
        assert CacheSchema.validate_cache_entry(entry) is False

        entry = {"created_at": "", "ttl": 60}
        assert CacheSchema.validate_cache_entry(entry) is False

    def test_is_expired_with_expires_at(self):
        # Not expired
        entry = {"expires_at": datetime.now(UTC).timestamp() + 100}
        assert CacheSchema.is_expired(entry) is False
        # Expired
        entry = {"expires_at": datetime.now(UTC).timestamp() - 10}
        assert CacheSchema.is_expired(entry) is True

    def test_is_expired_with_created_at_and_ttl(self):
        # Not expired
        entry = {
            "created_at": datetime.now(UTC).isoformat(),
            "ttl": 100,
        }
        assert CacheSchema.is_expired(entry) is False
        # Expired: use old timestamp
        old = datetime.now(UTC) - timedelta(seconds=200)
        entry = {"created_at": old.isoformat(), "ttl": 100}
        assert CacheSchema.is_expired(entry) is True

    def test_is_expired_fallback(self):
        # No expiry info
        assert CacheSchema.is_expired({}) is False


# ============================================================================
# Convenience function tests
# ============================================================================
def test_get_json_serializer_singleton():
    s1 = get_json_serializer()
    s2 = get_json_serializer()
    assert s1 is s2

def test_serialize_convenience():
    data = {"a": 1}
    serialized = serialize(data)
    assert isinstance(serialized, bytes)
    deserialized = deserialize(serialized)
    assert deserialized == data

def test_deserialize_none_convenience():
    assert deserialize(b"") is None
    assert deserialize(None) is None

def test_serialize_to_string_convenience():
    data = {"a": 1}
    s = serialize_to_string(data)
    assert isinstance(s, str)
    assert json.loads(s) == data

def test_deserialize_from_string_convenience():
    s = '{"a": 1}'
    data = deserialize_from_string(s)
    assert data == {"a": 1}
    assert deserialize_from_string("") is None
