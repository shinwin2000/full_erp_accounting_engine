"""Tempel/jalankan dari root project:  python diag_snippet.py"""
import sys
sys.path.insert(0, ".")

from infrastructure.persistence_orm.tax_transaction_table import TaxTransactionTable

print("=== __table__ columns ===")
print(sorted(TaxTransactionTable.__table__.columns.keys()))

print()
print("=== sqlalchemy.inspect() mapper.attrs ===")
try:
    from sqlalchemy import inspect as sa_inspect
    mapper = sa_inspect(TaxTransactionTable)
    print(sorted(mapper.attrs.keys()))
except Exception as e:
    print(f"INSPECT GAGAL: {type(e).__name__}: {e}")

print()
print("=== vars(cls) langsung (tanpa MRO) ===")
print(sorted(k for k in vars(TaxTransactionTable).keys() if not k.startswith("_")))
