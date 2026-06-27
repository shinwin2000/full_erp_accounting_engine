#!/usr/bin/env python3
"""
P50 Critical Modules Import Scan — Dynamic Standalone
Memastikan semua modul penting dapat diimpor tanpa error.
Mencari secara dinamis semua file .py di folder domain, aplikasi, infrastruktur, dll.
"""

import importlib
import logging
import pathlib
import sys
import time
from typing import List, Tuple

# Tambahkan root proyek ke sys.path agar modul dapat diimport
PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Konfigurasi logging minimal
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
# Redam log dari modul lain agar tidak mengganggu
logging.getLogger("sqlalchemy").setLevel(logging.WARNING)
logging.getLogger("infrastructure").setLevel(logging.WARNING)
logging.getLogger("adapters").setLevel(logging.WARNING)
logging.getLogger("bootstrap").setLevel(logging.WARNING)

# Folder yang dianggap penting untuk di-scan
CRITICAL_FOLDERS = {
    "domain", "application", "infrastructure", "adapters",
    "policy_engine", "ports", "kernel", "axioms", "constitution",
    "bootstrap", "config", "app", "event_gateway", "compliance",
    "audit", "projections", "reports"
}

# File yang harus di-skip (termasuk __init__.py)
SKIP_STEMS = {
    "__init__", "main_checker", "tax_checker", "layer_checker",
    "fiscal_period_checker", "checker_critical_import"
}

# Module yang tidak perlu di-scan karena sifatnya (proto, test, dll)
SKIP_MODULE_SUBSTR = {
    "proto", "test", "grpc", "pb2", "migrations"
}


def collect_modules() -> List[Tuple[str, str]]:
    """
    Kumpulkan semua modul penting sebagai (label, module_name).
    """
    modules = []
    for folder in CRITICAL_FOLDERS:
        dir_path = PROJECT_ROOT / folder
        if not dir_path.exists():
            continue
        for py_file in dir_path.rglob("*.py"):
            if py_file.stem in SKIP_STEMS:
                continue
            # Skip jika path mengandung substring yang tidak diinginkan
            if any(sub in str(py_file).lower() for sub in SKIP_MODULE_SUBSTR):
                continue
            # Ubah path menjadi module name
            rel_path = py_file.relative_to(PROJECT_ROOT)
            module_name = str(rel_path.with_suffix("")).replace("/", ".").replace("\\", ".")
            label = f"{folder}/{py_file.stem}"
            modules.append((label, module_name))
    # Urutkan berdasarkan label agar output konsisten
    modules.sort(key=lambda x: x[0])
    return modules


def safe_import(module_name: str) -> Tuple[bool, str]:
    """Coba import modul, kembalikan (success, error_message)."""
    try:
        importlib.import_module(module_name)
        return True, ""
    except ImportError as e:
        return False, f"ImportError: {e!s}"
    except SyntaxError as e:
        return False, f"SyntaxError: {e!s}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e!s}"


def main():
    print("=" * 70)
    print(" 🛡️ P50 CRITICAL MODULES IMPORT SCAN (Dynamic) 🛡️")
    print("=" * 70)
    print()

    start_time = time.monotonic()

    # Kumpulkan modul
    modules = collect_modules()
    total = len(modules)
    print(f"📦 Ditemukan {total} modul penting yang akan diperiksa.\n")

    # Variabel pelacakan
    success_count = 0
    failures = []  # list of (label, module, error)

    print("-" * 70)
    for idx, (label, module_name) in enumerate(modules, 1):
        # Tampilkan progres dengan padding
        print(f"[{idx:3d}/{total}] {label:50s} -> ", end="", flush=True)

        ok, err = safe_import(module_name)
        if ok:
            success_count += 1
            print("✅ OK")
        else:
            failures.append((label, module_name, err))
            print(f"❌ FAIL: {err[:60]}...")

    print("-" * 70)
    print()

    elapsed = time.monotonic() - start_time

    # Ringkasan
    print("=" * 70)
    print(f"Total modul:        {total}")
    print(f"Berhasil diimpor:   {success_count}")
    print(f"Gagal diimpor:      {len(failures)}")
    print(f"Durasi:             {elapsed:.2f} detik")
    print("=" * 70)

    if failures:
        print("\n🚨 [CRITICAL] Daftar modul yang gagal diimpor:")
        for label, module, err in failures[:20]:  # tampilkan 20 pertama
            print(f"  ❌ {label} ({module})")
            print(f"     Error: {err}")
        if len(failures) > 20:
            print(f"  ... dan {len(failures)-20} modul lainnya.")
        print("\n❌ STATUS: GAGAL — Sistem tidak siap deploy.")
        sys.exit(1)
    else:
        print("\n🎉 STATUS: 100% SUKSES — Semua modul penting dapat diimpor.")
        print("   Sistem siap untuk deployment.")
        sys.exit(0)


if __name__ == "__main__":
    main()