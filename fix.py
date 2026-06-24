from sqlalchemy import create_engine
from infrastructure.persistence_orm.base_model import Base
# Import semua model anda di sini agar Base.metadata mendeteksinya
# Contoh: from infrastructure.persistence_orm import (user, ledger, ...) 
# Pastikan semua file model yang memiliki kelas tabel di-import

# URL dari alembic.ini, diubah dari 'asyncpg' ke 'psycopg2'
DATABASE_URL = "postgresql+psycopg2://postgres:palapapls88@localhost:5432/erp_db"


engine = create_engine(DATABASE_URL)

def sync_schema():
    print("Mulai sinkronisasi schema ke database...")
    
    # Base.metadata.create_all akan membuat tabel yang belum ada
    # Berdasarkan struktur yang sudah dideklarasikan di kelas-kelas model Anda
    Base.metadata.create_all(engine)
    
    print("Sinkronisasi selesai! Database sudah diperbarui.")

if __name__ == "__main__":
    sync_schema()