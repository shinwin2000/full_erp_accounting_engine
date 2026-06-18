#!/usr/bin/env python3
"""Unit test untuk hash chain builder."""

from __future__ import annotations

import pytest

from audit.hash_chain_builder import GENESIS_HASH, get_audit_hash_builder


class TestAuditHashChainBuilder:
    @pytest.fixture
    def builder(self):
        return get_audit_hash_builder()

        @pytest.mark.asyncio
        async def test_build_chain(self, builder):
            events = [{"data": "a"}, {"data": "b"}, {"data": "c"}]
            chain = await builder.build_chain(events)
            assert len(chain) == 3
            assert chain[0]["previous_hash"] == GENESIS_HASH
            assert "hash" in chain[0]
            assert chain[1]["previous_hash"] == chain[0]["hash"]
            assert chain[2]["previous_hash"] == chain[1]["hash"]

            @pytest.mark.asyncio
            async def test_verify_chain_integrity(self, builder):
                events = [{"data": "a"}, {"data": "b"}]
                chain = await builder.build_chain(events)
                is_valid, broken_at, error = await builder.verify_chain(chain)
                assert is_valid is True
                assert broken_at is None
                assert error is None

                chain[1]["data"] = "x"
                is_valid, broken_at, error = await builder.verify_chain(chain)
                assert is_valid is False
                assert broken_at == 1

                @pytest.mark.asyncio
                async def test_find_broken_link(self, builder):
                    events = [{"data": "a"}, {"data": "b"}, {"data": "c"}]
                    chain = await builder.build_chain(events)
                    chain[1]["data"] = "modified"
                    broken_index = await builder.find_broken_link(chain)
                    assert broken_index == 1

                    @pytest.mark.asyncio
                    async def test_repair_chain(self, builder):
                        events = [{"data": "a"}, {"data": "b"}, {"data": "c"}]
                        chain = await builder.build_chain(events)
                        original_hashes = [e.get("hash") for e in chain]
                        chain[1]["data"] = "modified"
                        repaired = await builder.repair_chain(chain, start_index=1)
                        assert repaired[1]["hash"] != original_hashes[1]
                        assert repaired[2]["hash"] != original_hashes[2]
                        is_valid, _, _ = await builder.verify_chain(repaired)
                        assert is_valid is True

                        @pytest.mark.asyncio
                        async def test_get_last_hash(self, builder):
                            events = [{"data": "a"}, {"data": "b"}]
                            chain = await builder.build_chain(events)
                            last_hash = await builder.get_last_hash(chain)
                            assert last_hash == chain[-1]["hash"]

                            @pytest.mark.asyncio
                            async def test_get_chain_stats(self, builder):
                                events = [{"data": "a"}, {"data": "b"}]
                                chain = await builder.build_chain(events)
                                stats = await builder.get_chain_stats(chain)
                                assert stats["record_count"] == 2
                                assert stats["is_valid"] is True
                                assert stats["broken_at_index"] is None
                                assert stats["first_hash"] == chain[0]["hash"][:16] + "..."
                                assert stats["last_hash"] == chain[-1]["hash"][:16] + "..."

                                chain[1]["data"] = "x"
                                stats = await builder.get_chain_stats(chain)
                                assert stats["is_valid"] is False
                                assert stats["broken_at_index"] == 1

                                @pytest.mark.asyncio
                                async def test_clear_cache(self, builder):
                                    events = [{"data": "test"}]
                                    await builder.build_chain(events, stream_name="test_stream")
                                    assert "test_stream" in builder._cache
                                    await builder.clear_cache("test_stream")
                                    assert "test_stream" not in builder._cache
                                    await builder.clear_cache()
                                    assert len(builder._cache) == 0

                                    @pytest.mark.asyncio
                                    async def test_compute_record_hash(self, builder):
                                        record = {"data": "test", "id": "123"}
                                        previous_hash = GENESIS_HASH
                                        hash_val = builder.compute_record_hash(
                                            record, previous_hash
                                        )
                                        assert isinstance(hash_val, str)
                                        assert len(hash_val) == 64

                                        @pytest.mark.asyncio
                                        async def test_compute_batch_hash(self, builder):
                                            events = [{"data": "a"}, {"data": "b"}]
                                            chain = await builder.build_chain(events)
                                            batch_hash = builder.compute_batch_hash(chain)
                                            assert isinstance(batch_hash, str)
                                            assert len(batch_hash) == 64

                                            if __name__ == "__main__":
                                                pytest.main([__file__])
