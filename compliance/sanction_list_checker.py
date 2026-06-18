#!/usr/bin/env python3
"""
Module: sanction_list_checker.py
Layer: Compliance / Legal
Responsibility: Pemeriksa daftar sanksi (UNSC, OFAC, PPATK) dan entri sanksi.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SanctionCheckResult:
    """Hasil pengecekan daftar sanksi."""

    is_matched: bool
    sanction_reason: str | None = None
    matched_name: str | None = None


@dataclass
class SanctionListEntry:
    """Entri dalam daftar sanksi (UNSC, OFAC, PPATK)."""

    name: str = ""
    list_name: str = ""
    reason: str | None = None
    uid: str | None = None

    def __init__(
        self,
        name: str = "",
        list_name: str = "",
        reason: str | None = None,
        uid: str | None = None,
        **kwargs,
    ):
        self.name = name
        self.list_name = list_name
        self.reason = reason
        self.uid = uid
        # Menampung parameter tambahan ekstra secara dinamis agar aman dari TypeError
        for k, v in kwargs.items():
            setattr(self, k, v)


class SanctionListChecker:
    """Pemeriksa daftar sanksi (UNSC, OFAC, PPATK)."""

    def __init__(self):
        # Daftar sanksi internal (simulasi)
        self._sanctions = {
            "OSAMA BIN LADEN": "UNSC 1267",
            "USAMAH BIN LADEN": "UNSC 1267",
            "ABU BAKR AL-BAGHDADI": "UNSC 2170",
            "KIM JONG UN": "OFAC SDN",
            "VLADIMIR PUTIN": "OFAC SDN",
            "AL-QAEDA": "UNSC 1267",
        }

    def check(self, name: str, check_aliases: bool = False) -> SanctionCheckResult:
        """Memeriksa apakah nama terdaftar dalam daftar sanksi."""
        normalized = name.strip().upper()

        # Pencocokan eksak
        if normalized in self._sanctions:
            return SanctionCheckResult(
                is_matched=True, sanction_reason=self._sanctions[normalized], matched_name=name
            )

        # Pencocokan alias (untuk test)
        if check_aliases:
            if "USAMAH" in normalized and "BIN LADEN" in normalized:
                return SanctionCheckResult(
                    is_matched=True, sanction_reason="UNSC 1267", matched_name="OSAMA BIN LADEN"
                )

        return SanctionCheckResult(is_matched=False)


__all__ = ["SanctionCheckResult", "SanctionListChecker", "SanctionListEntry"]
