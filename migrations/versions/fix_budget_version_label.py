"""fix budget version_label column drift

Revision ID: fix_budget_version_label
Revises: inv_transfer_tables_005
Create Date: 2026-09-11

MASALAH:
Model ORM `BudgetTable` (infrastructure/persistence_orm/budget_table.py)
mendefinisikan dua kolom terpisah untuk tabel `budget`:
  - `version`       (Integer) -- dari VersionMixin, dipakai SQLAlchemy
                                  sebagai `version_id_col` untuk optimistic
                                  locking (nomor urut internal, BUKAN untuk
                                  ditampilkan ke user).
  - `version_label` (String)  -- field bisnis milik BudgetTable sendiri,
                                  contoh isinya "1.0", "Draft v2", dsb.
                                  Sengaja diberi nama beda dari `version`
                                  supaya tidak bentrok dengan atribut
                                  `version` milik VersionMixin di atas.

Migrasi ASLI (2cd2bd2d5b07_add_budget_table.py, dan duplikatnya di
0042_add_missing_orm_tables.py) ternyata cuma membuat SATU kolom bernama
`version` bertipe String -- dibuat SEBELUM kode ORM di-refactor jadi
`version_label`. Tidak ada migrasi lanjutan yang pernah menyesuaikan,
sehingga skema DB dan model ORM jadi tidak sinkron: query apa pun yang
menyentuh Budget (termasuk GET /api/v1/budget/budget/dashboard) gagal
dengan "column budget.version_label does not exist".

PERBAIKAN (idempotent -- aman dijalankan meski skema sudah campur aduk
akibat riwayat migrasi yang sempat drop/recreate tabel budget):
  1. Kalau kolom `version` (lama, String, berisi data asli seperti "1.0")
     ada tapi `version_label` belum ada -> **rename** `version` jadi
     `version_label` (data pengguna yang sudah ada tetap aman, tidak
     hilang).
  2. Kalau kolom `version` (Integer, untuk optimistic locking) belum ada
     -> tambahkan BARU dengan default 1 -- ini yang tadinya tidak pernah
     benar-benar dibuat sebagai Integer terpisah.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'fix_budget_version_label'
down_revision = 'inv_transfer_tables_005'
branch_labels = None
depends_on = None


def _column_info(table_name: str, column_name: str):
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for col in inspector.get_columns(table_name):
        if col["name"] == column_name:
            return col
    return None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "budget" not in inspector.get_table_names():
        # Tabel budget tidak ada sama sekali di database ini -- tidak ada
        # yang perlu diperbaiki (skenario instalasi baru yang migrasinya
        # sudah dirapikan di masa depan).
        return

    version_col = _column_info("budget", "version")
    version_label_col = _column_info("budget", "version_label")

    # 1) Rename kolom String lama `version` -> `version_label`, HANYA
    #    kalau version_label belum ada & version yang ada memang bertipe
    #    teks (bukan sudah Integer dari perbaikan sebelumnya).
    if version_label_col is None and version_col is not None:
        is_text_type = isinstance(version_col["type"], (sa.String, sa.Text, sa.VARCHAR))
        if is_text_type:
            op.alter_column("budget", "version", new_column_name="version_label")
            version_col = None  # sudah berpindah nama, dianggap tidak ada lagi
            version_label_col = _column_info("budget", "version_label")

    # Jaga-jaga: kalau ternyata version_label masih belum ada juga
    # (mis. tabel budget baru & kosong tanpa kolom version sama sekali),
    # tambahkan sebagai kolom baru.
    if version_label_col is None:
        op.add_column(
            "budget",
            sa.Column("version_label", sa.String(length=20), nullable=False, server_default="1.0"),
        )

    # 2) Pastikan ada kolom `version` Integer NOT NULL untuk optimistic
    #    locking (dipakai VersionMixin sebagai version_id_col).
    version_col = _column_info("budget", "version")
    if version_col is None:
        op.add_column(
            "budget",
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "budget" not in inspector.get_table_names():
        return
    if _column_info("budget", "version") is not None:
        op.drop_column("budget", "version")
    if _column_info("budget", "version_label") is not None:
        op.alter_column("budget", "version_label", new_column_name="version")
