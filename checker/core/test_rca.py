#!/usr/bin/env python3
"""
test_rca.py — pytest suite for rca.py (v5.0.0)
Run: pytest test_rca.py -v --tb=short
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import pytest
from rca import (
    Category,
    ErrorCode,
    RCAEngine,
    RCAResult,
    Severity,
    _ThreadSafeLRUCache,
    get_all_causes,
)

# Helper for severity ordering (replaces missing _SEVERITY_ORDER export)
_SEVERITY_ORDER = {s: s.order for s in Severity}


# ── Fixtures ──────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def engine():
    return RCAEngine()

# ── Helpers ───────────────────────────────────────────────────────────────────
def make_result(**kw):
    return RCAResult(severity=kw.pop("severity", Severity.INFO), **kw)

# ══════════════════════════════════════════════════════════════════════════════
# GROUP 1 — RCAResult data class
# ══════════════════════════════════════════════════════════════════════════════
class TestRCAResult:
    def test_confidence_clamp_upper(self):
        r = RCAResult(severity=Severity.HIGH, confidence=1.5)
        assert r.confidence == 1.0

    def test_confidence_clamp_lower(self):
        r = RCAResult(severity=Severity.LOW, confidence=-0.5)
        assert r.confidence == 0.0

    def test_confidence_valid_passthrough(self):
        r = RCAResult(severity=Severity.MEDIUM, confidence=0.75)
        assert r.confidence == 0.75

    def test_to_dict_basic(self):
        r = make_result(severity=Severity.HIGH, root_cause="test")
        d = r.to_dict()
        assert d["severity"] == "HIGH"
        assert d["root_cause"] == "test"

    def test_to_dict_no_circular_recursion(self):
        ra = make_result(severity=Severity.INFO)
        rb = make_result(severity=Severity.INFO)
        ra.children.append(rb)
        rb.children.append(ra)
        d = ra.to_dict()
        assert isinstance(d, dict)

    def test_to_json_returns_valid_json(self):
        import json
        r = make_result(severity=Severity.CRITICAL, root_cause="crash",
                        confidence=0.9)
        parsed = json.loads(r.to_json())
        assert parsed["severity"] == "CRITICAL"

    def test_error_code_is_enum(self):
        r = make_result(severity=Severity.HIGH,
                        error_code=ErrorCode.IMPORT_MODULE_NOT_FOUND)
        d = r.to_dict()
        assert d["error_code"] == "RCA001"

# ══════════════════════════════════════════════════════════════════════════════
# GROUP 2 — Error code & Severity
# ══════════════════════════════════════════════════════════════════════════════
class TestEnums:
    def test_errorcode_immutable(self):
        with pytest.raises((AttributeError, TypeError)):
            ErrorCode.UNKNOWN = "HACKED"  # type: ignore

    def test_severity_order_complete(self):
        for s in Severity:
            assert s in _SEVERITY_ORDER, f"{s} missing from _SEVERITY_ORDER"

    def test_severity_ordering(self):
        assert _SEVERITY_ORDER[Severity.FATAL] > _SEVERITY_ORDER[Severity.CRITICAL]
        assert _SEVERITY_ORDER[Severity.CRITICAL] > _SEVERITY_ORDER[Severity.HIGH]

# ══════════════════════════════════════════════════════════════════════════════
# GROUP 3 — Thread-safe LRU cache
# ══════════════════════════════════════════════════════════════════════════════
class TestLRUCache:
    def test_basic_set_get(self):
        c = _ThreadSafeLRUCache(10)
        c.set("k1", "v1")
        assert c.get("k1") == "v1"

    def test_miss_returns_none(self):
        c = _ThreadSafeLRUCache(10)
        assert c.get("nonexistent") is None

    def test_eviction_at_maxsize(self):
        c = _ThreadSafeLRUCache(2)
        c.set("a", 1); c.set("b", 2); c.set("c", 3)
        assert c.get("a") is None
        assert c.get("b") == 2
        assert c.get("c") == 3

    def test_clear(self):
        c = _ThreadSafeLRUCache(10)
        c.set("x", "y")
        c.clear()
        assert c.get("x") is None

    def test_tuple_key(self):
        c = _ThreadSafeLRUCache(10)
        key = ("file.py", 1234.5, 100, 10, 5)
        c.set(key, ["line1", "line2"])
        assert c.get(key) == ["line1", "line2"]

    def test_thread_safety(self):
        import threading
        c = _ThreadSafeLRUCache(100)
        errors = []
        def writer(i):
            try:
                for j in range(50):
                    c.set(f"k{i}_{j}", i * j)
            except Exception as e:
                errors.append(e)
        threads = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
        for t in threads: t.start()
        for t in threads: t.join()
        assert not errors

# ══════════════════════════════════════════════════════════════════════════════
# GROUP 4 — get_all_causes
# ══════════════════════════════════════════════════════════════════════════════
class TestGetAllCauses:
    def test_single_exception(self):
        e = ValueError("x")
        causes = get_all_causes(e)
        assert causes == [e]

    def test_chained_cause(self):
        try:
            try: raise ValueError("root")
            except ValueError as v:
                raise RuntimeError("wrap") from v
        except RuntimeError as e:
            causes = get_all_causes(e)
            assert len(causes) == 2
            assert any(isinstance(c, ValueError) for c in causes)

    def test_suppress_context_honored(self):
        try:
            try: raise ValueError("inner")
            except ValueError:
                raise RuntimeError("outer") from None
        except RuntimeError as e:
            causes = get_all_causes(e)
            assert all(not isinstance(c, ValueError) for c in causes)

    def test_no_duplicate(self):
        e = RuntimeError("x")
        causes = get_all_causes(e)
        assert len(causes) == len(set(id(c) for c in causes))

# ══════════════════════════════════════════════════════════════════════════════
# GROUP 5 — Engine behaviour (disingkat)
# ══════════════════════════════════════════════════════════════════════════════
class TestRCAEngine:
    def test_engine_has_rules(self, engine):
        assert len(engine._rules) >= 30

    def test_analyze_never_raises(self, engine):
        for exc in [
            ValueError("x"), TypeError("y"), RuntimeError("z"),
            KeyError("k"), AttributeError("a"), ImportError("i"),
            ConnectionError("c"), MemoryError(), RecursionError(),
            PermissionError("p"), FileNotFoundError("f"),
        ]:
            r = engine.analyze(exc)
            assert r is not None

    def test_stats_keys_present(self, engine):
        s = engine.stats()
        for top_key in ("engine", "cache", "rules"):
            assert top_key in s, f"Missing top-level key: {top_key}"
        engine_stats = s.get("engine", {})
        for eng_key in ("total_analyses", "total_time", "version", "rule_count"):
            assert eng_key in engine_stats, f"Missing engine key: {eng_key}"

    def test_result_confidence_in_range(self, engine):
        for exc in [ValueError("test"), RuntimeError("test"), TypeError("test")]:
            r = engine.analyze(exc)
            assert 0.0 <= r.confidence <= 1.0, f"confidence={r.confidence}"

    def test_fallback_for_unknown_exception(self, engine):
        class _WeirdError(Exception): pass
        try: raise _WeirdError("something odd")
        except Exception as e:
            r = engine.analyze(e)
        assert r is not None
        assert r.error_code == ErrorCode.UNKNOWN

    def test_exception_chain_analyzed(self, engine):
        try:
            try: raise ValueError("root cause")
            except ValueError as v:
                raise RuntimeError("surface error") from v
        except Exception as e:
            r = engine.analyze(e)
        assert r is not None

    def test_thread_safety_concurrent_analyze(self, engine):
        import threading
        errors = []
        results = []
        def worker():
            try:
                try: raise AttributeError("test")
                except Exception as e:
                    r = engine.analyze(e)
                    results.append(r)
            except Exception as ex:
                errors.append(ex)
        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads: t.start()
        for t in threads: t.join()
        assert not errors
        assert len(results) == 20
        assert all(r.category == Category.ATTRIBUTE for r in results)

# ── Jalankan langsung ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
