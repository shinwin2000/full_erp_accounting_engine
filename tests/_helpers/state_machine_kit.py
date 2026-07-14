"""
tests/_helpers/state_machine_kit.py
=====================================
Helper generik untuk menguji SELURUH matriks transisi status (state machine)
sebuah entity dalam SATU test, alih-alih menulis satu test per pasangan
transisi secara manual (yang tidak realistis untuk 650 titik transisi).

Kenapa "matrix test" dan bukan cuma "assert can_transition(DRAFT, POSTED) is True"?
-------------------------------------------------------------------------------
1. Cakupan penuh: N status = N*N pasangan. Satu test parametrized menutupi
   SEMUA pasangan (valid maupun invalid), bukan cuma jalur bahagia.
2. Regression-proof: hasil transisi di-snapshot eksplisit sebagai literal di
   file test (lihat generator di bawah). Kalau nanti seseorang mengubah
   `_ALLOWED_TRANSITIONS` tanpa sengaja, test ini GAGAL dan memaksa
   perubahan itu di-review secara sadar — inilah nilai SOX/audit-nya.
3. Negative path otomatis ikut ter-cover (checker Tier-1 "Negative Path"
   akan naik juga, bukan cuma Tier-6 "State Transition").

Cara pakai lihat contoh test yang di-generate oleh
tools/generate_state_transition_tests.py.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest


def assert_transition_matrix(
    expected: dict[tuple[Any, Any], bool],
    transition_fn: Callable[[Any, Any], bool],
) -> None:
    """Menjalankan can_transition(from, to) untuk SETIAP pasangan di
    `expected` dan membandingkan dengan nilai yang di-snapshot.

    `expected` : dict {(from_status, to_status): True/False}
    `transition_fn` : callable(from_status, to_status) -> bool

    Kalau ada mismatch, semua mismatch dikumpulkan dan dilaporkan sekaligus
    (bukan berhenti di kegagalan pertama) supaya sekali jalan langsung
    kelihatan semua pasangan yang berubah perilakunya.
    """
    mismatches: list[str] = []
    for (frm, to), expected_result in expected.items():
        actual_result = transition_fn(frm, to)
        if actual_result != expected_result:
            mismatches.append(
                f"  {frm!r} -> {to!r}: expected {expected_result}, got {actual_result}"
            )
    if mismatches:
        pytest.fail(
            "State transition matrix berubah dari snapshot yang di-generate!\n"
            "Kalau perubahan ini DISENGAJA, regenerate test-nya dengan:\n"
            "  python tools/generate_state_transition_tests.py --only <module>\n"
            "Kalau TIDAK disengaja, ini bug regresi pada state machine:\n"
            + "\n".join(mismatches)
        )


def assert_terminal_states_have_no_outgoing_transitions(
    statuses: list[Any],
    transition_fn: Callable[[Any, Any], bool],
    terminal_statuses: set[Any],
) -> None:
    """Invariant tambahan: status yang dianggap 'terminal' (mis. CANCELLED,
    REVERSED) tidak boleh punya jalur keluar ke status manapun kecuali yang
    eksplisit di-whitelist oleh domain (mis. REVERSED -> ARCHIVED)."""
    violations = []
    for term in terminal_statuses:
        for to in statuses:
            if to != term and transition_fn(term, to):
                violations.append(f"  {term!r} -> {to!r} seharusnya tidak mungkin (status terminal)")
    if violations:
        pytest.fail("Terminal state punya jalur keluar yang tidak diharapkan:\n" + "\n".join(violations))


def assert_no_self_transition(
    statuses: list[Any],
    transition_fn: Callable[[Any, Any], bool],
    allowed_self_transitions: set[Any] | None = None,
) -> None:
    """Invariant: `can_transition(X, X)` umumnya harus False (tidak ada
    transisi ke diri sendiri), kecuali status yang memang di-whitelist
    (mis. status 'DRAFT' yang boleh di-update berulang tanpa pindah status)."""
    allowed_self_transitions = allowed_self_transitions or set()
    violations = [
        f"  {s!r} -> {s!r} seharusnya False"
        for s in statuses
        if s not in allowed_self_transitions and transition_fn(s, s)
    ]
    if violations:
        pytest.fail("Self-transition tidak diharapkan ditemukan:\n" + "\n".join(violations))
