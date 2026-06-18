from __future__ import annotations

"""
Package: infrastructure.event_store
Immutable event store, hash chain, tamper detection.
"""

from infrastructure.event_store.append_only_store import AppendOnlyStore, get_event_store
from infrastructure.event_store.hash_chain_builder import HashChainBuilder
from infrastructure.event_store.tamper_detection_scanner import TamperDetectionScanner

__all__ = [
    "AppendOnlyStore",
    "HashChainBuilder",
    "TamperDetectionScanner",
    "get_event_store",
]
