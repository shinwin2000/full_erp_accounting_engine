# test_hash_chain_link_vo.py
# ===========================
# Comprehensive tests for domain/shared_value_objects/hash_chain_link_vo.py.
# Covers all public methods, properties, factory methods, verification,
# serialization, helper functions, and edge cases.

import hashlib
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from domain.shared_value_objects.hash_chain_link_vo import (
    HashChainError,
    HashChainLinkVO,
    HashVerificationError,
    IdempotencyManager,
    InvalidHashError,
    combine_hashes,
    compute_chain_root_hash,
    hash_data,
    validate_hash_string,
)


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------
@pytest.fixture
def sample_data() -> dict:
    return {"transaction_id": "TXN001", "amount": Decimal("1000")}


@pytest.fixture
def genesis_link(sample_data) -> HashChainLinkVO:
    return HashChainLinkVO.create_first(sample_data, metadata={"type": "transaction"})


@pytest.fixture
def second_link(genesis_link, sample_data) -> HashChainLinkVO:
    data2 = {"transaction_id": "TXN002", "amount": Decimal("500")}
    return HashChainLinkVO.create_next(genesis_link, data2, metadata={"type": "transaction2"})


# ----------------------------------------------------------------------
# Exceptions
# ----------------------------------------------------------------------
class TestExceptions:
    def test_hash_chain_error(self):
        err = HashChainError("test")
        assert isinstance(err, ValueError)

    def test_hash_verification_error(self):
        err = HashVerificationError("test")
        assert isinstance(err, HashChainError)

    def test_invalid_hash_error(self):
        err = InvalidHashError("test")
        assert isinstance(err, HashChainError)


# ----------------------------------------------------------------------
# IdempotencyManager
# ----------------------------------------------------------------------
class TestIdempotencyManager:
    def test_construction(self):
        mgr = IdempotencyManager()
        assert mgr._storage == {}
        assert mgr._ttl_seconds == 86400

    def test_get_cached_result_not_found(self):
        mgr = IdempotencyManager()
        result = mgr.get_cached_result("key", "method")
        assert result is None

    def test_cache_and_retrieve(self):
        mgr = IdempotencyManager()
        mgr.cache_result("key", "method", {"data": "value"})
        result = mgr.get_cached_result("key", "method")
        assert result == {"data": "value"}

    def test_cache_expired(self):
        mgr = IdempotencyManager()
        mgr.cache_result("key", "method", {"data": "value"})
        # Patch datetime.now to go past TTL
        with patch("domain.shared_value_objects.hash_chain_link_vo.datetime") as mock_dt:
            mock_dt.now.return_value = datetime.now(UTC) + timedelta(seconds=86401)
            result = mgr.get_cached_result("key", "method")
            assert result is None

    def test_different_methods_have_different_keys(self):
        mgr = IdempotencyManager()
        mgr.cache_result("key", "method1", {"data": "value1"})
        result1 = mgr.get_cached_result("key", "method1")
        assert result1 == {"data": "value1"}
        result2 = mgr.get_cached_result("key", "method2")
        assert result2 is None


# ----------------------------------------------------------------------
# HashChainLinkVO - Construction & Validation
# ----------------------------------------------------------------------
class TestHashChainLinkVOConstruction:
    def test_construction_valid(self, genesis_link):
        assert genesis_link.previous_hash is None
        assert genesis_link.current_hash is not None
        assert len(genesis_link.current_hash) == 64
        assert genesis_link.data_hash is not None
        assert genesis_link.version == 1
        assert genesis_link.metadata == {"type": "transaction"}
        assert genesis_link.timestamp.tzinfo == UTC

    def test_construction_invalid_previous_hash_non_hex(self):
        with pytest.raises(InvalidHashError, match="previous_hash must be 64 hex chars"):
            HashChainLinkVO(
                previous_hash="not_hex",
                current_hash="a" * 64,
                timestamp=datetime.now(UTC),
                data_hash="a" * 64,
                version=1,
            )

    def test_construction_invalid_previous_hash_length(self):
        with pytest.raises(InvalidHashError, match="previous_hash must be 64 hex chars"):
            HashChainLinkVO(
                previous_hash="a" * 63,
                current_hash="a" * 64,
                timestamp=datetime.now(UTC),
                data_hash="a" * 64,
                version=1,
            )

    def test_construction_invalid_current_hash_non_hex(self):
        with pytest.raises(InvalidHashError, match="current_hash must be 64 hex chars"):
            HashChainLinkVO(
                previous_hash=None,
                current_hash="not_hex",
                timestamp=datetime.now(UTC),
                data_hash="a" * 64,
                version=1,
            )

    def test_construction_invalid_data_hash_non_hex(self):
        with pytest.raises(InvalidHashError, match="data_hash must be 64 hex chars"):
            HashChainLinkVO(
                previous_hash=None,
                current_hash="a" * 64,
                timestamp=datetime.now(UTC),
                data_hash="not_hex",
                version=1,
            )

    def test_construction_version_negative_raises(self):
        with pytest.raises(HashChainError, match="version must be >= 1"):
            HashChainLinkVO(
                previous_hash=None,
                current_hash="a" * 64,
                timestamp=datetime.now(UTC),
                data_hash="a" * 64,
                version=0,
            )

    def test_construction_naive_timestamp_auto_utc(self):
        naive = datetime(2025, 1, 1, 10, 0, 0)
        link = HashChainLinkVO(
            previous_hash=None,
            current_hash="a" * 64,
            timestamp=naive,
            data_hash="a" * 64,
            version=1,
        )
        assert link.timestamp.tzinfo == UTC
        assert link.timestamp == naive.replace(tzinfo=UTC)

    def test_construction_invalid_metadata_type_raises(self):
        with pytest.raises(HashChainError, match="metadata must be dict or None"):
            HashChainLinkVO(
                previous_hash=None,
                current_hash="a" * 64,
                timestamp=datetime.now(UTC),
                data_hash="a" * 64,
                version=1,
                metadata="not_dict",  # type: ignore
            )


# ----------------------------------------------------------------------
# HashChainLinkVO - Factory Methods (create_first, create_next)
# ----------------------------------------------------------------------
class TestHashChainLinkVOFactory:
    def test_create_first_with_dict(self, sample_data):
        link = HashChainLinkVO.create_first(sample_data)
        assert link.previous_hash is None
        assert link.version == 1
        # Compute expected data_hash
        json_str = json.dumps(sample_data, sort_keys=True, separators=(",", ":"))
        expected_data_hash = hashlib.sha3_256(json_str.encode()).hexdigest()
        assert link.data_hash == expected_data_hash
        expected_current = hashlib.sha3_256(f"{expected_data_hash}|".encode()).hexdigest()
        assert link.current_hash == expected_current

    def test_create_first_with_string(self):
        data = "test string"
        link = HashChainLinkVO.create_first(data)
        expected_data_hash = hashlib.sha3_256(data.encode()).hexdigest()
        assert link.data_hash == expected_data_hash

    def test_create_first_with_bytes(self):
        data = b"test bytes"
        link = HashChainLinkVO.create_first(data)
        expected_data_hash = hashlib.sha3_256(data).hexdigest()
        assert link.data_hash == expected_data_hash

    def test_create_first_unsupported_type_raises(self):
        with pytest.raises(HashChainError, match="Unsupported data type"):
            HashChainLinkVO.create_first(123)  # type: ignore

    def test_create_first_with_metadata_and_timestamp(self):
        ts = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
        link = HashChainLinkVO.create_first(
            {"key": "value"}, metadata={"user": "alice"}, timestamp=ts
        )
        assert link.timestamp == ts
        assert link.metadata == {"user": "alice"}

    def test_create_first_with_idempotency_key(self, sample_data):
        with patch("domain.shared_value_objects.hash_chain_link_vo._idempotency_manager") as mock_mgr:
            mock_mgr.get_cached_result.return_value = None
            mock_mgr.cache_result.return_value = None
            link = HashChainLinkVO.create_first(sample_data, idempotency_key="key-123")
            mock_mgr.get_cached_result.assert_called_once_with("key-123", "create_first")
            mock_mgr.cache_result.assert_called_once()
            assert link is not None

    def test_create_first_idempotency_cache_hit(self, sample_data):
        with patch("domain.shared_value_objects.hash_chain_link_vo._idempotency_manager") as mock_mgr:
            cached = {
                "previous_hash": None,
                "current_hash": "a" * 64,
                "timestamp": datetime.now(UTC).isoformat(),
                "data_hash": "b" * 64,
                "version": 1,
                "metadata": {"cached": True},
            }
            mock_mgr.get_cached_result.return_value = cached
            link = HashChainLinkVO.create_first(sample_data, idempotency_key="key-123")
            assert link.previous_hash is None
            assert link.current_hash == "a" * 64
            assert link.data_hash == "b" * 64
            assert link.version == 1
            assert link.metadata == {"cached": True}
            mock_mgr.cache_result.assert_not_called()

    def test_create_next(self, genesis_link, sample_data):
        data2 = {"transaction_id": "TXN002"}
        link2 = HashChainLinkVO.create_next(genesis_link, data2)
        assert link2.previous_hash == genesis_link.current_hash
        assert link2.version == 2
        expected_data_hash = HashChainLinkVO._compute_data_hash(data2)
        assert link2.data_hash == expected_data_hash
        expected_current = HashChainLinkVO._compute_link_hash(expected_data_hash, genesis_link.current_hash)
        assert link2.current_hash == expected_current

    def test_create_next_with_idempotency_key(self, genesis_link, sample_data):
        with patch("domain.shared_value_objects.hash_chain_link_vo._idempotency_manager") as mock_mgr:
            mock_mgr.get_cached_result.return_value = None
            mock_mgr.cache_result.return_value = None
            HashChainLinkVO.create_next(genesis_link, sample_data, idempotency_key="key-next")
            mock_mgr.get_cached_result.assert_called_once_with("key-next", "create_next")
            mock_mgr.cache_result.assert_called_once()

    def test_create_next_cache_hit(self, genesis_link, sample_data):
        with patch("domain.shared_value_objects.hash_chain_link_vo._idempotency_manager") as mock_mgr:
            cached = {
                "previous_hash": genesis_link.current_hash,
                "current_hash": "a" * 64,
                "timestamp": datetime.now(UTC).isoformat(),
                "data_hash": "b" * 64,
                "version": 2,
                "metadata": {"cached": True},
            }
            mock_mgr.get_cached_result.return_value = cached
            link2 = HashChainLinkVO.create_next(genesis_link, sample_data, idempotency_key="key-next")
            assert link2.previous_hash == genesis_link.current_hash
            assert link2.current_hash == "a" * 64
            assert link2.data_hash == "b" * 64
            assert link2.version == 2
            assert link2.metadata == {"cached": True}

    def test_create_next_naive_timestamp_converted(self, genesis_link, sample_data):
        naive = datetime(2025, 1, 1, 12, 0, 0)
        link2 = HashChainLinkVO.create_next(genesis_link, sample_data, timestamp=naive)
        assert link2.timestamp.tzinfo == UTC
        assert link2.timestamp == naive.replace(tzinfo=UTC)

    def test_from_dict(self, genesis_link):
        d = genesis_link.to_dict(include_full_hash=True)
        reconstructed = HashChainLinkVO.from_dict(d)
        assert reconstructed.previous_hash == genesis_link.previous_hash
        assert reconstructed.current_hash == genesis_link.current_hash
        assert reconstructed.data_hash == genesis_link.data_hash
        assert reconstructed.version == genesis_link.version
        assert reconstructed.metadata == genesis_link.metadata
        assert reconstructed.timestamp == genesis_link.timestamp


# ----------------------------------------------------------------------
# HashChainLinkVO - Properties (is_genesis, short_*)
# ----------------------------------------------------------------------
class TestHashChainLinkVOProperties:
    def test_is_genesis_true(self, genesis_link):
        assert genesis_link.is_genesis is True

    def test_is_genesis_false(self, second_link):
        assert second_link.is_genesis is False

    def test_short_current_hash(self, genesis_link):
        short = genesis_link.short_current_hash
        assert short == genesis_link.current_hash[:16] + "..."

    def test_short_previous_hash_genesis(self, genesis_link):
        assert genesis_link.short_previous_hash is None

    def test_short_previous_hash_non_genesis(self, second_link):
        short = second_link.short_previous_hash
        assert short is not None
        assert short == second_link.previous_hash[:16] + "..."

    def test_short_data_hash(self, genesis_link):
        short = genesis_link.short_data_hash
        assert short == genesis_link.data_hash[:16] + "..."


# ----------------------------------------------------------------------
# HashChainLinkVO - Verification (verify, verify_chain)
# ----------------------------------------------------------------------
class TestHashChainLinkVOVerification:
    def test_verify_success(self, genesis_link, sample_data):
        # verify should return True for valid data
        assert genesis_link.verify(sample_data) is True

    def test_verify_data_hash_mismatch_raises(self, genesis_link):
        wrong_data = {"transaction_id": "WRONG"}
        with pytest.raises(HashVerificationError, match="Data hash mismatch"):
            genesis_link.verify(wrong_data)

    def test_verify_current_hash_mismatch_raises(self, genesis_link, sample_data):
        # Tamper with the link by setting a wrong current_hash (can't mutate frozen, but we can create a new one)
        # Create a link with wrong current_hash but same data_hash
        data_hash = genesis_link.data_hash
        wrong_current = HashChainLinkVO._compute_link_hash(data_hash, "some_previous")  # wrong previous
        link = HashChainLinkVO(
            previous_hash=None,
            current_hash=wrong_current,
            timestamp=genesis_link.timestamp,
            data_hash=data_hash,
            version=1,
        )
        with pytest.raises(HashVerificationError, match="Current hash mismatch"):
            link.verify(sample_data)

    def test_verify_chain_continuity_success(self, genesis_link, second_link):
        # Create a third link
        data3 = {"transaction_id": "TXN003"}
        third_link = HashChainLinkVO.create_next(second_link, data3)
        # verify_chain starting from genesis
        links = [genesis_link, second_link, third_link]
        assert genesis_link.verify_chain(links, 0) is True

    def test_verify_chain_continuity_failure(self, genesis_link, second_link):
        # Create a link that breaks the chain (previous_hash mismatch)
        broken_link = HashChainLinkVO(
            previous_hash="a" * 64,  # wrong previous_hash
            current_hash=hashlib.sha3_256(b"test").hexdigest(),
            timestamp=datetime.now(UTC),
            data_hash=hashlib.sha3_256(b"data").hexdigest(),
            version=3,
        )
        links = [genesis_link, second_link, broken_link]
        with pytest.raises(HashVerificationError, match="Chain break at index 1"):
            genesis_link.verify_chain(links, 0)


# ----------------------------------------------------------------------
# HashChainLinkVO - Serialization
# ----------------------------------------------------------------------
class TestHashChainLinkVOSerialization:
    def test_to_dict_truncated(self, genesis_link):
        d = genesis_link.to_dict(include_full_hash=False)
        assert d["previous_hash"] is None
        assert d["current_hash"] == genesis_link.short_current_hash
        assert d["data_hash"] == genesis_link.short_data_hash
        assert d["version"] == 1
        assert d["algorithm"] == "sha3-256"
        assert d["timestamp"] == genesis_link.timestamp.isoformat()

    def test_to_dict_full(self, genesis_link):
        d = genesis_link.to_dict(include_full_hash=True)
        assert d["previous_hash"] is None
        assert d["current_hash"] == genesis_link.current_hash
        assert d["data_hash"] == genesis_link.data_hash
        assert d["version"] == 1
        assert d["algorithm"] == "sha3-256"

    def test_to_db_record(self, genesis_link):
        rec = genesis_link.to_db_record()
        assert rec["previous_hash"] is None
        assert rec["current_hash"] == genesis_link.current_hash
        assert rec["data_hash"] == genesis_link.data_hash
        assert rec["version"] == 1
        assert rec["timestamp"] == genesis_link.timestamp
        assert rec["metadata"] == json.dumps(genesis_link.metadata)

    def test_to_db_record_metadata_none(self):
        link = HashChainLinkVO.create_first({"a": 1})
        rec = link.to_db_record()
        assert rec["metadata"] is None

    def test_from_db_record(self, genesis_link):
        rec = genesis_link.to_db_record()
        reconstructed = HashChainLinkVO.from_db_record(rec)
        assert reconstructed.previous_hash == genesis_link.previous_hash
        assert reconstructed.current_hash == genesis_link.current_hash
        assert reconstructed.data_hash == genesis_link.data_hash
        assert reconstructed.version == genesis_link.version
        assert reconstructed.timestamp == genesis_link.timestamp
        assert reconstructed.metadata == genesis_link.metadata

    def test_from_db_record_metadata_json(self):
        link = HashChainLinkVO.create_first({"a": 1}, metadata={"user": "bob"})
        rec = link.to_db_record()
        reconstructed = HashChainLinkVO.from_db_record(rec)
        assert reconstructed.metadata == {"user": "bob"}


# ----------------------------------------------------------------------
# HashChainLinkVO - Dunder methods
# ----------------------------------------------------------------------
class TestHashChainLinkVODunder:
    def test_str(self, genesis_link):
        assert str(genesis_link) == f"HashChainLink(v{genesis_link.version}, hash={genesis_link.short_current_hash})"

    def test_repr(self, genesis_link):
        assert repr(genesis_link) == f"HashChainLinkVO(version={genesis_link.version}, hash={genesis_link.short_current_hash}, prev=None)"

    def test_equality(self, genesis_link, second_link):
        # Two links with same current_hash are equal
        same = HashChainLinkVO(
            previous_hash=None,
            current_hash=genesis_link.current_hash,
            timestamp=genesis_link.timestamp,
            data_hash=genesis_link.data_hash,
            version=1,
        )
        assert genesis_link == same
        assert genesis_link != second_link
        assert genesis_link != "not a link"

    def test_hash(self, genesis_link):
        assert hash(genesis_link) == hash(genesis_link.current_hash)


# ----------------------------------------------------------------------
# Helper Functions
# ----------------------------------------------------------------------
class TestHelperFunctions:
    def test_compute_chain_root_hash(self, genesis_link, second_link):
        links = [genesis_link, second_link]
        root = compute_chain_root_hash(links)
        expected = hashlib.sha3_256(
            (genesis_link.current_hash + second_link.current_hash).encode()
        ).hexdigest()
        assert root == expected

    def test_compute_chain_root_hash_empty_raises(self):
        with pytest.raises(HashChainError, match="Cannot compute root hash of empty chain"):
            compute_chain_root_hash([])

    def test_validate_hash_string_valid(self):
        valid = "a" * 64
        assert validate_hash_string(valid) is True

    def test_validate_hash_string_invalid_length(self):
        assert validate_hash_string("a" * 63) is False

    def test_validate_hash_string_invalid_char(self):
        assert validate_hash_string("g" * 64) is False

    def test_validate_hash_string_non_string(self):
        assert validate_hash_string(123) is False

    def test_hash_data_dict(self):
        data = {"key": "value", "num": 1}
        json_str = json.dumps(data, sort_keys=True, separators=(",", ":"))
        expected = hashlib.sha3_256(json_str.encode()).hexdigest()
        assert hash_data(data) == expected

    def test_hash_data_str(self):
        data = "hello"
        expected = hashlib.sha3_256(b"hello").hexdigest()
        assert hash_data(data) == expected

    def test_hash_data_bytes(self):
        data = b"hello"
        expected = hashlib.sha3_256(b"hello").hexdigest()
        assert hash_data(data) == expected

    def test_hash_data_unsupported_raises(self):
        with pytest.raises(TypeError, match="Cannot hash type"):
            hash_data(123)

    def test_combine_hashes(self):
        h1 = "a" * 64
        h2 = "b" * 64
        expected = hashlib.sha3_256((h1 + h2).encode()).hexdigest()
        assert combine_hashes(h1, h2) == expected


# ----------------------------------------------------------------------
# Integration: Full chain creation and verification
# ----------------------------------------------------------------------
def test_full_chain_scenario():
    # Create genesis
    data1 = {"event": "start", "amount": 1000}
    genesis = HashChainLinkVO.create_first(data1, metadata={"type": "start"})

    # Add second
    data2 = {"event": "middle", "amount": 500}
    link2 = HashChainLinkVO.create_next(genesis, data2, metadata={"type": "middle"})

    # Add third
    data3 = {"event": "end", "amount": 0}
    link3 = HashChainLinkVO.create_next(link2, data3, metadata={"type": "end"})

    # Verify each link's data
    assert genesis.verify(data1) is True
    assert link2.verify(data2) is True
    assert link3.verify(data3) is True

    # Verify chain continuity
    links = [genesis, link2, link3]
    assert genesis.verify_chain(links, 0) is True

    # Check root hash
    root = compute_chain_root_hash(links)
    assert root is not None

    # Tamper with data2 and verify should fail
    wrong_data2 = {"event": "middle", "amount": 600}
    with pytest.raises(HashVerificationError):
        link2.verify(wrong_data2)

    # Serialize and reconstruct
    rec = link2.to_db_record()
    reconstructed = HashChainLinkVO.from_db_record(rec)
    assert reconstructed == link2
