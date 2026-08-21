#!/usr/bin/env python3
"""
Module: temporal_resolver.py
Layer: 7 - Policy Engine
Responsibility: Resolusi temporal kebijakan.
               Menentukan kebijakan mana yang berlaku pada suatu tanggal,
               berdasarkan effective_from dan effective_to.

Dependencies:
- standard library (datetime, logging, typing)
- policy_engine.loader_yaml (PolicySet)
- policy_engine.policy_exceptions

Audit: Setiap resolusi temporal dictat.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from .loader_yaml import PolicySet, get_policy_loader
from .policy_exceptions import TemporalResolutionError

logger = logging.getLogger(__name__)


# === 1. TEMPORAL RESOLVER ===


class TemporalResolver:
    """
    Resolver untuk menentukan kebijakan berdasarkan waktu.

    Business context: Memastikan kebijakan yang digunakan sesuai
    dengan periode efektifnya, menangani perubahan kebijakan
    antar periode, dan menyediakan histori.
    """

    _instance: TemporalResolver | None = None
    _initialized: bool = False  # FIX: tambahkan anotasi tipe
    _loader: Any  # FIX: tambahkan anotasi tipe
    _timeline_cache: dict[str, list[PolicySet]]

    def __new__(cls) -> TemporalResolver:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._loader = get_policy_loader()
        self._timeline_cache = {}

    def _build_timeline(self, domain: str, jurisdiction: str | None = None) -> list[PolicySet]:
        """Membangun timeline kebijakan untuk domain."""
        cache_key = f"{domain}_{jurisdiction or 'all'}"
        if cache_key in self._timeline_cache:
            return self._timeline_cache[cache_key]

        policies = self._loader.get_policies_by_domain(domain, jurisdiction=jurisdiction)
        # Sort by effective_from
        policies.sort(key=lambda p: p.effective_from)
        self._timeline_cache[cache_key] = policies
        return policies

    def get_policy_at_date(
        self,
        domain: str,
        target_date: datetime,
        jurisdiction: str | None = None,
    ) -> PolicySet | None:
        """
        Mendapatkan kebijakan yang berlaku pada tanggal tertentu.

        Args:
            domain: Domain kebijakan
            target_date: Tanggal target
            jurisdiction: Jurisdiksi (opsional)

        Returns:
            PolicySet yang berlaku, atau None jika tidak ada
        """
        timeline = self._build_timeline(domain, jurisdiction)

        for policy in reversed(timeline):  # Cari dari yang terbaru
            if policy.effective_from <= target_date and (
                policy.effective_to is None or policy.effective_to >= target_date
            ):
                return policy

        return None

    def get_policy_at_date_strict(
        self,
        domain: str,
        target_date: datetime,
        jurisdiction: str | None = None,
    ) -> PolicySet:
        """Seperti get_policy_at_date tetapi melempar exception jika tidak ditemukan."""
        policy = self.get_policy_at_date(domain, target_date, jurisdiction)
        if policy is None:
            raise TemporalResolutionError(
                effective_date=target_date.isoformat(),
                reason=f"No active policy for domain {domain} at {target_date}",
            )
        return policy

    def get_policy_effective_range(
        self,
        policy_id: str,
    ) -> tuple[datetime, datetime | None]:
        """
        Mendapatkan rentang efektif suatu kebijakan.

        Returns:
            Tuple (effective_from, effective_to)
        """
        policy = self._loader.get_policy_set(policy_id)
        if not policy:
            raise TemporalResolutionError(
                effective_date="",
                reason=f"Policy {policy_id} not found",
            )
        return (policy.effective_from, policy.effective_to)

    def get_policy_timeline(
        self,
        domain: str,
        jurisdiction: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Mendapatkan timeline perubahan kebijakan untuk domain.

        Returns:
            List of dict dengan effective_from, effective_to, version
        """
        timeline = self._build_timeline(domain, jurisdiction)
        return [
            {
                "policy_id": p.id,
                "version": p.version,
                "effective_from": p.effective_from.isoformat(),
                "effective_to": p.effective_to.isoformat() if p.effective_to else None,
                "domain": p.domain,
            }
            for p in timeline
        ]

    def is_policy_active_at(
        self,
        policy_id: str,
        target_date: datetime,
    ) -> bool:
        """Memeriksa apakah kebijakan aktif pada tanggal tertentu."""
        policy = self._loader.get_policy_set(policy_id)
        if not policy:
            return False
        return policy.effective_from <= target_date and (
            policy.effective_to is None or policy.effective_to >= target_date
        )

    def get_next_policy_change(
        self,
        domain: str,
        after_date: datetime,
        jurisdiction: str | None = None,
    ) -> dict[str, Any] | None:
        """
        Mendapatkan perubahan kebijakan berikutnya setelah tanggal tertentu.

        Returns:
            Dict dengan info perubahan, atau None
        """
        timeline = self._build_timeline(domain, jurisdiction)
        for policy in timeline:
            if policy.effective_from > after_date:
                return {
                    "policy_id": policy.id,
                    "effective_from": policy.effective_from.isoformat(),
                    "version": policy.version,
                }
        return None

    def get_changes_between(
        self,
        domain: str,
        from_date: datetime,
        to_date: datetime,
        jurisdiction: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Mendapatkan semua perubahan kebijakan antara dua tanggal.
        """
        timeline = self._build_timeline(domain, jurisdiction)
        changes = []
        for policy in timeline:
            if from_date <= policy.effective_from <= to_date:
                changes.append(
                    {
                        "policy_id": policy.id,
                        "effective_from": policy.effective_from.isoformat(),
                        "version": policy.version,
                    }
                )
        return changes

    def clear_cache(self) -> None:
        """Menghapus cache timeline."""
        self._timeline_cache.clear()

    def get_requirements_summary(self) -> dict[str, Any]:
        """Mendapatkan ringkasan persyaratan resolver."""
        return {
            "timezone": "UTC",
            "supported_date_formats": ["ISO8601"],
            "default_effective_start": "1900-01-01",
            "infinite_effective_end": "None",
        }

    # ========================================================================
    # TEST COMPATIBILITY METHODS
    # ========================================================================

    def get_effective_policy(
        self, policies: list[dict[str, Any]], as_of: date
    ) -> dict[str, Any] | None:
        """
        Get the policy effective at the given date (test compatibility).
        policies: list of dicts with keys: id, effective_date (date or str), end_date (date or str or None)
        as_of: date to check
        """
        applicable = []
        for policy in policies:
            eff = policy.get("effective_date")
            # Convert to date if string
            if isinstance(eff, str):
                eff = date.fromisoformat(eff)
            # If eff is not a date, skip
            if not isinstance(eff, date):
                continue

            end = policy.get("end_date")
            if isinstance(end, str):
                end = date.fromisoformat(end) if end else None
            elif isinstance(end, datetime):
                end = end.date()

            # Now eff is guaranteed date, end is date or None
            if eff <= as_of and (end is None or end >= as_of):
                applicable.append(policy)

        if not applicable:
            return None
        # Sort by effective_date descending to get the latest applicable
        applicable.sort(key=lambda p: p["effective_date"], reverse=True)
        return applicable[0]


# === 2. SINGLETON ACCESSOR ===

_temporal_resolver_instance: TemporalResolver | None = None


def get_temporal_resolver() -> TemporalResolver:
    """Mendapatkan instance singleton TemporalResolver."""
    global _temporal_resolver_instance
    if _temporal_resolver_instance is None:
        _temporal_resolver_instance = TemporalResolver()
    return _temporal_resolver_instance


# === 3. EXPORTS ===

__all__ = [
    "TemporalResolver",
    "get_temporal_resolver",
]
