#!/usr/bin/env python3
"""
Module: iam_session_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Alias untuk IAMSessionTable (forward compatibility).

CATATAN ARSITEKTUR:
    Semua definisi tabel IAM (termasuk IAMSessionTable) dipusatkan di
    iam_user_table.py untuk menghindari konflik SQLAlchemy mapper registry
    akibat duplikat class name atau konflik UniqueConstraint/Index saat
    dua file mendefinisikan tabel yang sama (iam_session).

    File ini hanya menjadi re-export alias agar import path lama tetap
    berfungsi tanpa perlu mengubah seluruh codebase.
"""

from __future__ import annotations

from infrastructure.persistence_orm.iam_user_table import IAMSessionTable

__all__ = ["IAMSessionTable"]
