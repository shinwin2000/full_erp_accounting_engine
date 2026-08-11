"""coa leaf-node enforcement trigger + journal_line account snapshot columns

Dua perbaikan independen:

1. LEAF-NODE RULE (COA): akun dengan allow_posting=true tidak boleh punya
   sub-akun (child), dan akun yang sudah punya child tidak boleh diubah
   menjadi allow_posting=true. Ini dijaga dengan trigger PostgreSQL
   (BEFORE INSERT/UPDATE) supaya berlaku ATOMIK dan tidak bisa dilewati
   walau ada yang menulis langsung lewat SQL/koneksi lain di luar service
   ini — bukan hanya validasi di level aplikasi (Python), yang bisa saja
   diabaikan oleh jalur kode lain di masa depan.

   Catatan: draft awal (dari diskusi dengan asisten lain) mengusulkan CHECK
   CONSTRAINT dengan subquery EXISTS, tapi PostgreSQL TIDAK MENGIZINKAN
   subquery di dalam CHECK CONSTRAINT. Karena itu aturan ini diimplementasikan
   sebagai trigger, bukan CHECK constraint.

2. SNAPSHOT KOLOM DI journal_line: `account_name` sudah ada sebelumnya tapi
   tidak pernah diisi; ditambah `account_type_snapshot` dan
   `normal_balance_snapshot`. Snapshot ini diisi otomatis saat baris jurnal
   dibuat (lihat sqlalchemy_journal_repository_impl.py::_to_orm_lines) agar
   laporan keuangan historis tetap benar walau atribut akun di COA berubah
   di kemudian hari.

Revision ID: 0048coa2
Revises: 0047coa
Create Date: 2026-08-08 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0048coa2"
down_revision: Union[str, None] = "0047coa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Snapshot kolom di journal_line
    # ------------------------------------------------------------------
    op.add_column("journal_line", sa.Column("account_type_snapshot", sa.String(20), nullable=True))
    op.add_column("journal_line", sa.Column("normal_balance_snapshot", sa.String(6), nullable=True))

    # Backfill baris lama (kalau ada) dari data account saat ini — hanya
    # best-effort (akun mungkin sudah berubah sejak jurnal lama dibuat, tapi
    # ini jauh lebih baik daripada NULL untuk laporan lama).
    op.execute(
        """
        UPDATE journal_line jl
        SET account_type_snapshot = a.account_type,
            normal_balance_snapshot = a.normal_balance,
            account_name = COALESCE(jl.account_name, a.account_name)
        FROM account a
        WHERE a.account_code = jl.account_code
          AND a.legal_entity_id = jl.legal_entity_id
          AND jl.account_type_snapshot IS NULL
        """
    )

    # ------------------------------------------------------------------
    # 2. Trigger leaf-node rule di tabel account
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION enforce_coa_leaf_node_rule()
        RETURNS TRIGGER AS $$
        DECLARE
            parent_allow_posting BOOLEAN;
            child_exists BOOLEAN;
        BEGIN
            -- Aturan A: akun baru/diubah yang punya parent, parent-nya
            -- tidak boleh sedang allow_posting=true (parent harus header).
            IF NEW.parent_account_id IS NOT NULL THEN
                SELECT allow_posting INTO parent_allow_posting
                FROM account WHERE id = NEW.parent_account_id;

                IF parent_allow_posting IS TRUE THEN
                    RAISE EXCEPTION
                        'COA_LEAF_NODE_VIOLATION: parent account is a posting account (allow_posting=true) and cannot have child accounts'
                        USING ERRCODE = '23514';
                END IF;
            END IF;

            -- Aturan B: akun tidak boleh diubah jadi allow_posting=true
            -- kalau sudah punya child.
            IF NEW.allow_posting IS TRUE THEN
                SELECT EXISTS(
                    SELECT 1 FROM account WHERE parent_account_id = NEW.id
                ) INTO child_exists;

                IF child_exists THEN
                    RAISE EXCEPTION
                        'COA_LEAF_NODE_VIOLATION: cannot set allow_posting=true, this account already has child accounts'
                        USING ERRCODE = '23514';
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_coa_leaf_node_rule
        BEFORE INSERT OR UPDATE ON account
        FOR EACH ROW EXECUTE FUNCTION enforce_coa_leaf_node_rule();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_coa_leaf_node_rule ON account;")
    op.execute("DROP FUNCTION IF EXISTS enforce_coa_leaf_node_rule();")
    op.drop_column("journal_line", "normal_balance_snapshot")
    op.drop_column("journal_line", "account_type_snapshot")
