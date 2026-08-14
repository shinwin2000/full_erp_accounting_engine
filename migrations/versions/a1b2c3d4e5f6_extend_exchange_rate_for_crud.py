"""extend_exchange_rate_for_crud

ForexService tidak pernah didaftarkan ke IoC container (fixed sebelumnya)
DAN tidak punya method list/create/get/update/deactivate/lock/unlock
exchange rate sama sekali, padahal fastapi_forex_router.py sudah
memanggilnya sejak awal. Menambahkan method2 itu butuh kolom yang belum
ada di tabel exchange_rate: rate_type, status, is_locked, locked_by,
locked_at. Juga memperbaiki CHECK constraint ck_exchange_rate_source yang
whitelist-nya tidak pernah disinkronkan dengan RateProvider enum di
router (bloomberg/reuters/bank_bca/dst akan selalu gagal INSERT).

Revision ID: a1b2c3d4e5f6
Revises: f6a7b8c9d0e1
Create Date: 2026-08-13 06:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'a11627f45a52'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    for ddl in (
        "ALTER TABLE exchange_rate ADD COLUMN IF NOT EXISTS rate_type VARCHAR(20) NOT NULL DEFAULT 'mid'",
        "ALTER TABLE exchange_rate ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'active'",
        "ALTER TABLE exchange_rate ADD COLUMN IF NOT EXISTS is_locked BOOLEAN NOT NULL DEFAULT false",
        "ALTER TABLE exchange_rate ADD COLUMN IF NOT EXISTS locked_by UUID",
        "ALTER TABLE exchange_rate ADD COLUMN IF NOT EXISTS locked_at TIMESTAMPTZ",
    ):
        bind.execute(text(ddl))

    # RateProvider enum di router jauh lebih lengkap (bloomberg, reuters,
    # bank_bca, bank_mandiri, bank_bri, bank_bni, custom) dibanding
    # whitelist CHECK constraint lama (cuma 5 nilai) - insert manapun yang
    # pakai provider di luar 5 itu akan selalu gagal. Ganti whitelist-nya
    # supaya sinkron dengan enum RateProvider.
    bind.execute(text("ALTER TABLE exchange_rate DROP CONSTRAINT IF EXISTS ck_exchange_rate_source;"))
    bind.execute(text("""
        ALTER TABLE exchange_rate ADD CONSTRAINT ck_exchange_rate_source
        CHECK (source IN (
            'manual', 'bank_indonesia', 'bloomberg', 'reuters',
            'bank_bca', 'bank_mandiri', 'bank_bri', 'bank_bni', 'custom',
            'central_bank', 'internal', 'api'
        ));
    """))

    bind.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_exchange_rate_status ON exchange_rate (status);"
    ))


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_exchange_rate_status;")
    op.execute("ALTER TABLE exchange_rate DROP COLUMN IF EXISTS rate_type;")
    op.execute("ALTER TABLE exchange_rate DROP COLUMN IF EXISTS status;")
    op.execute("ALTER TABLE exchange_rate DROP COLUMN IF EXISTS is_locked;")
    op.execute("ALTER TABLE exchange_rate DROP COLUMN IF EXISTS locked_by;")
    op.execute("ALTER TABLE exchange_rate DROP COLUMN IF EXISTS locked_at;")
