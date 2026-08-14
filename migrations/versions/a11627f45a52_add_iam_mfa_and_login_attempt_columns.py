"""add_iam_mfa_and_login_attempt_columns

Modul Keamanan Akun (Sesi, MFA & Password) di frontend
(ui/pages/iam_security_page.py) memanggil endpoint MFA
(/iam/iam/mfa/setup, /verify, /disable) dan menampilkan Riwayat
Percobaan Login, tapi keduanya selalu gagal/kosong karena:

1. Tabel iam_user tidak pernah punya kolom mfa_enabled/mfa_secret/
   mfa_backup_codes sama sekali sejak awal (migration 0003), padahal
   domain UserEntity.enable_mfa()/disable_mfa() sudah mengasumsikan
   kolom ini ada. Endpoint MFA sebelumnya cuma stub 501 karena tidak
   ada tempat menyimpan secret-nya.
2. adapters/secondary_impl/.../record_login_attempt() sebelumnya
   menulis failure_reason ke kolom "user_agent" yang TIDAK ADA di
   tabel iam_login_attempt (migration 0004/0043) - ini akan
   TypeError kalau sampai dipanggil. Menambahkan kolom user_agent
   dan failure_reason yang sesungguhnya supaya riwayat percobaan
   login bisa dicatat dengan benar dan lengkap.
3. Endpoint /forgot-password dan /reset-password sebelumnya dummy
   total (selalu balas "(dummy)" tanpa pernah mengganti password
   siapapun). Menambahkan kolom password_reset_token_hash dan
   password_reset_expires_at supaya token reset password sekali-
   pakai bisa disimpan (dalam bentuk hash, bukan plaintext) dan
   divalidasi masa berlakunya.

Revision ID: a11627f45a52
Revises: f6a7b8c9d0e1
Create Date: 2026-08-14 08:00:00.000000

CATATAN REVISI: revision id file ini sebelumnya 'e5f6a7b8c9d0' dengan
down_revision 'd4e5f6a7b8c9' - ternyata 'e5f6a7b8c9d0' sudah dipakai
migration lain di repo ini (fix_consolidation_group_name_uniqueness)
yang tidak ikut ter-include di snapshot kode yang sempat direview,
menyebabkan "Multiple head revisions". File di-rename + revision id
diganti acak (bukan pola sekuensial lagi) + down_revision diarahkan
ke head chain yang benar (f6a7b8c9d0e1).
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = 'a11627f45a52'
down_revision: Union[str, None] = 'f6a7b8c9d0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    for ddl in (
        "ALTER TABLE iam_user ADD COLUMN IF NOT EXISTS "
        "mfa_enabled BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE iam_user ADD COLUMN IF NOT EXISTS "
        "mfa_secret VARCHAR(255)",
        "ALTER TABLE iam_user ADD COLUMN IF NOT EXISTS "
        "mfa_backup_codes JSONB",
        "ALTER TABLE iam_user ADD COLUMN IF NOT EXISTS "
        "password_reset_token_hash VARCHAR(255)",
        "ALTER TABLE iam_user ADD COLUMN IF NOT EXISTS "
        "password_reset_expires_at TIMESTAMPTZ",
        "CREATE INDEX IF NOT EXISTS idx_iam_user_reset_token "
        "ON iam_user (password_reset_token_hash)",
        "ALTER TABLE iam_login_attempt ADD COLUMN IF NOT EXISTS "
        "user_agent VARCHAR(500)",
        "ALTER TABLE iam_login_attempt ADD COLUMN IF NOT EXISTS "
        "failure_reason VARCHAR(255)",
    ):
        bind.execute(text(ddl))


def downgrade() -> None:
    op.execute("ALTER TABLE iam_login_attempt DROP COLUMN IF EXISTS failure_reason;")
    op.execute("ALTER TABLE iam_login_attempt DROP COLUMN IF EXISTS user_agent;")
    op.execute("DROP INDEX IF EXISTS idx_iam_user_reset_token;")
    op.execute("ALTER TABLE iam_user DROP COLUMN IF EXISTS password_reset_expires_at;")
    op.execute("ALTER TABLE iam_user DROP COLUMN IF EXISTS password_reset_token_hash;")
    op.execute("ALTER TABLE iam_user DROP COLUMN IF EXISTS mfa_backup_codes;")
    op.execute("ALTER TABLE iam_user DROP COLUMN IF EXISTS mfa_secret;")
    op.execute("ALTER TABLE iam_user DROP COLUMN IF EXISTS mfa_enabled;")
