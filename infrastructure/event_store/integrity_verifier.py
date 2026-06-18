# infrastructure/event_store/integrity_verifier.py
"""
Module: integrity_verifier.py
Layer: Infrastructure (Event Store)
Responsibility: Verifikasi integritas event store. Memastikan hash chain utuh,
               tidak ada event yang hilang, timestamp ordering valid, dan
               tidak ada manipulasi data.
Dependencies:
- asyncio, hashlib, json, logging, datetime
- infrastructure.event_store.append_only_store (AppendOnlyStore)
- infrastructure.event_store.hash_chain_builder (HashChainBuilder)
Audit: Setiap verifikasi dicatat dan jika ditemukan pelanggaran, trigger alert.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import Any

from infrastructure.event_store.append_only_store import AppendOnlyStore, get_event_store
from infrastructure.event_store.hash_chain_builder import HashChainBuilder
from infrastructure.telemetry.alert_manager_router import trigger_alert

logger = logging.getLogger(__name__)


class IntegrityVerifier:
    """
    Verifikator integritas event store.

    Fitur:
    - Verifikasi hash chain untuk setiap stream
    - Verifikasi tidak ada event yang hilang (gap sequence)
    - Verifikasi timestamp ordering
    - Verifikasi data integrity (recalculate hash)
    - Generate integrity report
    """

    def __init__(self, event_store: AppendOnlyStore | None = None):
        self._event_store = event_store
        self._hash_builder = HashChainBuilder()

    async def _get_event_store(self) -> AppendOnlyStore:
        if self._event_store is None:
            self._event_store = await get_event_store()
        return self._event_store

    async def verify_stream_integrity(self, stream_name: str) -> dict[str, Any]:
        """
        Verifikasi integritas untuk satu stream.

        Returns:
            Dictionary dengan hasil verifikasi
        """
        event_store = await self._get_event_store()
        events = await event_store.read_stream(stream_name, limit=1_000_000)

        if not events:
            return {
                "stream_name": stream_name,
                "is_valid": True,
                "event_count": 0,
                "errors": [],
            }

        errors = []
        last_sequence = 0
        last_hash = None
        last_timestamp = None

        for i, event in enumerate(events):
            seq = event.get("sequence_number", i + 1)
            # Cek gap sequence
            if seq != last_sequence + 1 and last_sequence != 0:
                errors.append(f"Sequence gap at event {i}: expected {last_sequence + 1}, got {seq}")
            last_sequence = seq

            # Verifikasi hash
            data = event.get("data", {})
            metadata = event.get("metadata", {})
            timestamp_str = event.get("timestamp")
            if timestamp_str and isinstance(timestamp_str, str):
                timestamp = datetime.fromisoformat(timestamp_str)
            else:
                timestamp = datetime.now(UTC)

            prev_hash = event.get("previous_hash")
            current_hash = event.get("hash")

            # Recalculate hash
            content = {
                "data": data,
                "metadata": metadata,
                "timestamp": timestamp.isoformat(),
                "previous_hash": prev_hash,
            }
            json_str = json.dumps(content, sort_keys=True, default=str)
            computed_hash = hashlib.sha256(json_str.encode("utf-8")).hexdigest()

            if computed_hash != current_hash:
                errors.append(
                    f"Hash mismatch at event {seq}: stored={current_hash}, computed={computed_hash}"
                )

            # Cek chain continuity
            if last_hash is not None and prev_hash != last_hash:
                errors.append(
                    f"Chain break at event {seq}: prev_hash={prev_hash}, expected={last_hash}"
                )

            last_hash = current_hash

            # Cek timestamp ordering (harus monoton)
            if last_timestamp is not None and timestamp < last_timestamp:
                errors.append(
                    f"Timestamp out of order at event {seq}: {timestamp} < {last_timestamp}"
                )
            last_timestamp = timestamp

        return {
            "stream_name": stream_name,
            "is_valid": len(errors) == 0,
            "event_count": len(events),
            "errors": errors,
            "first_sequence": events[0].get("sequence_number", 1) if events else None,
            "last_sequence": last_sequence,
            "first_timestamp": events[0].get("timestamp") if events else None,
            "last_timestamp": last_timestamp.isoformat() if last_timestamp else None,
        }

    async def verify_all_streams(
        self,
        max_concurrent: int = 5,
        on_progress: Callable[[str, int, int], None] | None = None,
    ) -> dict[str, Any]:
        """
        Verifikasi semua stream dalam event store.

        Args:
            max_concurrent: Maksimum concurrent verification
            on_progress: Callback progress (stream_name, current, total)

        Returns:
            Ringkasan verifikasi
        """
        event_store = await self._get_event_store()
        # Dapatkan semua stream name
        streams = await event_store.list_streams()

        total = len(streams)
        results = {}
        semaphore = asyncio.Semaphore(max_concurrent)

        async def verify_one(stream_name: str, idx: int):
            async with semaphore:
                if on_progress:
                    on_progress(stream_name, idx + 1, total)
                result = await self.verify_stream_integrity(stream_name)
                return stream_name, result

        tasks = [verify_one(stream, i) for i, stream in enumerate(streams)]
        verified = await asyncio.gather(*tasks)
        for stream_name, result in verified:
            results[stream_name] = result

        # Ringkasan
        total_events = sum(r["event_count"] for r in results.values())
        valid_streams = sum(1 for r in results.values() if r["is_valid"])
        invalid_streams = total - valid_streams
        all_errors = []
        for stream_name, result in results.items():
            if not result["is_valid"]:
                all_errors.extend([f"{stream_name}: {e}" for e in result["errors"]])

        summary = {
            "total_streams": total,
            "valid_streams": valid_streams,
            "invalid_streams": invalid_streams,
            "total_events": total_events,
            "all_valid": invalid_streams == 0,
            "errors": all_errors[:100],  # batasi 100 error
        }

        # Trigger alert jika ada yang tidak valid
        if not summary["all_valid"]:
            await trigger_alert(
                title="Event Store Integrity Violation",
                message=f"{invalid_streams} streams failed integrity check",
                severity="critical",
                source="IntegrityVerifier",
                details={"invalid_streams": [s for s, r in results.items() if not r["is_valid"]]},
            )
            logger.error(f"Integrity check failed: {invalid_streams} invalid streams")

        logger.info(f"Integrity check completed: {valid_streams}/{total} streams valid")
        return summary

    async def verify_hash_chain(self, stream_name: str) -> bool:
        """
        Verifikasi hash chain untuk stream (menggunakan HashChainBuilder).

        Returns:
            True jika chain valid, False jika tidak
        """
        event_store = await self._get_event_store()
        events = await event_store.read_stream(stream_name, limit=1_000_000)

        # Konversi ke format yang dibutuhkan HashChainBuilder
        chain_events = []
        for ev in events:
            chain_events.append(
                {
                    "data": ev.get("data", {}),
                    "metadata": ev.get("metadata", {}),
                    "timestamp": ev.get("timestamp"),
                    "previous_hash": ev.get("previous_hash"),
                    "hash": ev.get("hash"),
                    "sequence_number": ev.get("sequence_number"),
                }
            )

        is_valid, broken_at, error = await self._hash_builder.verify_chain(chain_events)
        if not is_valid:
            logger.warning(f"Hash chain invalid for {stream_name} at {broken_at}: {error}")
        return is_valid

    async def verify_no_missing_events(self, stream_name: str) -> dict[str, Any]:
        """
        Verifikasi tidak ada event yang hilang (gap sequence) pada stream.

        Returns:
            Dictionary dengan informasi gap
        """
        event_store = await self._get_event_store()
        events = await event_store.read_stream(stream_name, limit=1_000_000)

        gaps = []
        last_seq = 0
        for event in events:
            seq = event.get("sequence_number", 0)
            if seq != last_seq + 1 and last_seq != 0:
                gaps.append({"expected": last_seq + 1, "actual": seq})
            last_seq = seq

        return {
            "stream_name": stream_name,
            "has_gaps": len(gaps) > 0,
            "gaps": gaps,
            "first_sequence": events[0].get("sequence_number") if events else None,
            "last_sequence": last_seq,
        }

    async def generate_integrity_report(self, output_path: str | None = None) -> str:
        """
        Generate laporan integritas lengkap dalam format JSON.

        Args:
            output_path: Path untuk menyimpan laporan (opsional)

        Returns:
            String JSON laporan
        """
        report = {
            "timestamp": datetime.now(UTC).isoformat(),
            "verifier": "IntegrityVerifier",
        }

        # Verifikasi semua stream
        summary = await self.verify_all_streams()
        report["summary"] = summary

        # Detail per stream (limit untuk laporan besar)
        streams_detail = {}
        for stream_name, result in summary.get("stream_details", {}).items():
            streams_detail[stream_name] = {
                "is_valid": result["is_valid"],
                "event_count": result["event_count"],
                "error_count": len(result.get("errors", [])),
            }
        report["streams"] = streams_detail

        import json

        report_json = json.dumps(report, indent=2, default=str)

        if output_path:
            with open(output_path, "w") as f:
                f.write(report_json)
            logger.info(f"Integrity report saved to {output_path}")

        return report_json

    async def quick_check(self) -> bool:
        """
        Pemeriksaan cepat: apakah event store sehat.
        Memeriksa genesis event dan beberapa stream sampel.

        Returns:
            True jika sehat, False jika tidak
        """
        event_store = await self._get_event_store()
        try:
            # Cek genesis event
            genesis = await event_store.get_last_event("__system__")
            if not genesis:
                logger.error("Genesis event not found")
                return False

            # Cek beberapa stream sampel (max 10)
            streams = await event_store.list_streams(limit=10)
            for stream in streams:
                result = await self.verify_stream_integrity(stream)
                if not result["is_valid"]:
                    logger.warning(f"Stream {stream} integrity check failed")
                    return False

            return True

        except Exception as e:
            logger.error(f"Quick check failed: {e}")
            return False


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_integrity_verifier: IntegrityVerifier | None = None


async def get_integrity_verifier() -> IntegrityVerifier:
    """Get singleton instance of IntegrityVerifier."""
    global _integrity_verifier
    if _integrity_verifier is None:
        _integrity_verifier = IntegrityVerifier()
    return _integrity_verifier


__all__ = ["IntegrityVerifier", "get_integrity_verifier"]
