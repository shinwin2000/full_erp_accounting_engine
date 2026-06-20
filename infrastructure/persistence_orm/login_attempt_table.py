#!/usr/bin/env python3
"""
Module: login_attempt_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Alias untuk LoginAttemptTable (forward compatibility).

CATATAN ARSITEKTUR:
    Semua definisi tabel IAM (termasuk LoginAttemptTable) dipusatkan di
    iam_user_table.py untuk menghindari konflik SQLAlchemy mapper registry
    akibat duplikat class name atau double-import tabel yang sama.

    File ini hanya menjadi re-export alias agar import path lama tetap
    berfungsi tanpa perlu mengubah seluruh codebase.
"""

from __future__ import annotations

from infrastructure.persistence_orm.iam_user_table import LoginAttemptTable

__all__ = ["LoginAttemptTable"]
