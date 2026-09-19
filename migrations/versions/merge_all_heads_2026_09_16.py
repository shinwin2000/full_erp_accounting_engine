"""Merge all divergent migration heads into one

Repo ini punya 8 revision head yang tumbuh independen dari waktu ke waktu
(kemungkinan besar dari beberapa sesi kerja terpisah yang masing-masing
menambah migrasi linear sendiri tanpa pernah di-rebase ke state
terbaru). Ditemukan saat audit modul Goodwill 2026-09-16, ketika migrasi
baru (goodwill_disposal_001) ikut menjadi head ke-8 dan
`alembic upgrade head` gagal karena ambigu.

Migrasi ini TIDAK melakukan DDL apa pun (upgrade/downgrade kosong) -
satu-satunya tujuannya adalah menyatukan 8 head jadi satu titik lewat
down_revision berupa tuple, sesuai mekanisme merge standar Alembic.
Ini murni perubahan metadata graph migrasi, aman dijalankan kapan saja.

PENTING - baca sebelum menjalankan `alembic upgrade head` setelah ini:
Menyatukan graph TIDAK menjamin ke-8 cabang itu bebas konflik DDL satu
sama lain (mis. dua cabang berbeda sama-sama membuat tabel/kolom yang
sama). Migrasi ini hanya menyelesaikan masalah "head ambigu" - bukan
memverifikasi isi ke-8 cabang itu sendiri. Jalankan `alembic current`
DULU untuk melihat revisi mana saja yang sudah benar-benar tercatat
diterapkan di database Anda, sebelum menjalankan upgrade sungguhan.

Revision ID: merge_all_heads_2026_09_16
Revises: 0001abcd, 0003abcd, 0042abcd, 0045abcd, 4d83d4738911,
         fix_po_so_schema, goodwill_disposal_001, journal_header_fix_001
"""
from __future__ import annotations

revision = "merge_all_heads_2026_09_16"
down_revision = (
    "0001abcd",
    "0003abcd",
    "0042abcd",
    "0045abcd",
    "4d83d4738911",
    "fix_po_so_schema",
    "goodwill_disposal_001",
    "journal_header_fix_001",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Tidak ada DDL - murni menyatukan graph migrasi."""
    pass


def downgrade() -> None:
    """Tidak ada DDL untuk dibalik."""
    pass
