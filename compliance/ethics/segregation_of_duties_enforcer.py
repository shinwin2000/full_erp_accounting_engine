#!/usr/bin/env python3
"""
Module: segregation_of_duties_enforcer.py
Layer: Compliance / Ethics
Responsibility: Menerapkan pemisahan tugas (Segregation of Duties) sesuai SOX.
"""

from __future__ import annotations


class SodEnforcer:
    """
    Enforcer untuk aturan pemisahan tugas (SOD).
    Memastikan user tidak memiliki kombinasi peran yang konflik.
    """

    # Daftar konflik tugas (role yang tidak boleh dimiliki oleh user yang sama)
    CONFLICTING_ACTIONS: dict[str, set[str]] = {
        "journal.create": {"journal.approve", "journal.post"},
        "journal.approve": {"journal.create", "journal.post"},
        "journal.post": {"journal.create", "journal.approve"},
        "cash.disburse": {"cash.approve", "bank.reconcile"},
        "bank.reconcile": {"cash.disburse", "journal.create"},
        "purchase.order": {"goods.receive", "ap.invoice"},
        "ap.invoice": {"purchase.order", "payment.execute"},
        "payment.execute": {"ap.invoice", "bank.reconcile"},
    }

    def __init__(self):
        self._user_roles: dict[str, set[str]] = {}

    def assign_role(self, user_id: str, action: str) -> None:
        """Berikan akses suatu action ke user."""
        if user_id not in self._user_roles:
            self._user_roles[user_id] = set()
        self._user_roles[user_id].add(action)

    def can_perform(self, user_id: str, action: str) -> bool:
        """
        Periksa apakah user diizinkan melakukan action tertentu.
        True jika tidak ada konflik dengan action lain yang sudah dimiliki user.
        """
        if user_id not in self._user_roles:
            return False

        user_actions = self._user_roles[user_id]
        # Cek apakah ada konflik dengan action yang diminta
        if action in self.CONFLICTING_ACTIONS:
            conflicting = self.CONFLICTING_ACTIONS[action]
            if user_actions.intersection(conflicting):
                return False
        # Juga cek apakah action yang diminta akan menyebabkan konflik dengan action yang sudah ada
        for existing in user_actions:
            if (
                existing in self.CONFLICTING_ACTIONS
                and action in self.CONFLICTING_ACTIONS[existing]
            ):
                return False
        return True
