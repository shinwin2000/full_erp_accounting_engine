import sys
import os
from pathlib import Path

# ========== 1. Tentukan root proyek ==========
ROOT = Path(__file__).resolve().parent
ROOT_STR = str(ROOT)

# ========== 2. Bersihkan sys.path dari duplikasi dan path yang mencurigakan ==========
# Hapus semua entri yang mengarah ke ROOT (agar kita bisa menambahkan dengan posisi yang tepat)
sys.path = [p for p in sys.path if p != ROOT_STR]

# Tambahkan ROOT di posisi paling depan
if ROOT_STR not in sys.path:
    sys.path.insert(0, ROOT_STR)

print(f"[conftest] ROOT: {ROOT_STR}")
print(f"[conftest] sys.path[0]: {sys.path[0]}")

# ========== 3. Pastikan infrastructure diimport sebagai package ==========
try:
    import infrastructure
    if hasattr(infrastructure, '__path__'):
        print("[conftest] infrastructure adalah package (__path__ ada)")
    else:
        print("[conftest] WARNING: infrastructure BUKAN package, perbaiki...")
        # Hapus dari sys.modules dan import ulang
        if 'infrastructure' in sys.modules:
            del sys.modules['infrastructure']
        import infrastructure as infra
        sys.modules['infrastructure'] = infra
        print("[conftest] infrastructure diperbaiki")
except ImportError as e:
    print(f"[conftest] Gagal import infrastructure: {e}")
    sys.exit(1)

# ========== 4. Pastikan infrastruktur submodul juga bisa diimport ==========
try:
    import infrastructure.telemetry
    print("[conftest] infrastructure.telemetry berhasil diimport")
except ImportError as e:
    print(f"[conftest] Gagal import infrastructure.telemetry: {e}")