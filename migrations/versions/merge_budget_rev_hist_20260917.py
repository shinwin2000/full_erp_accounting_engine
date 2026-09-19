"""Merge budget_revision_history branch into the unified head

Cabang b1a2c3d4e5f6 (add_budget_revision_history_table) dibuat dari
snapshot lama bercabang di 'fix_budget_version_label' - titik yang sama
dengan asal cabang fix_po_so_schema yang sudah disatukan lewat
merge_all_heads_2026_09_16. File ini baru muncul di mesin pengguna
setelah merge sebelumnya dibuat, sehingga jadi head kedua yang terpisah.

Migrasi ini TIDAK melakukan DDL apa pun - murni menyatukan 2 head
menjadi 1 lewat down_revision berupa tuple, sesuai mekanisme merge
standar Alembic.

FIX: percobaan pertama pakai revision id "merge_budget_revision_history_
2026_09_17" (41 karakter) - gagal saat upgrade karena kolom
alembic_version.version_num di database ini dibatasi VARCHAR(32).
Transaksinya otomatis rollback (aman, tidak ada state korup), tapi
revision id-nya harus dipendekkan supaya muat. Nama di bawah ini 30
karakter.

Revision ID: merge_budget_rev_hist_20260917
Revises: b1a2c3d4e5f6, merge_all_heads_2026_09_16
"""
from __future__ import annotations

revision = "merge_budget_rev_hist_20260917"
down_revision = (
    "b1a2c3d4e5f6",
    "merge_all_heads_2026_09_16",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Tidak ada DDL - murni menyatukan graph migrasi."""
    pass


def downgrade() -> None:
    """Tidak ada DDL untuk dibalik."""
    pass
