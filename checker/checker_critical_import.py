#!/usr/bin/env python3
"""
P50 Critical Modules Import Scan — Standalone Test
Memastikan semua modul kritis dapat diimpor tanpa error.
Jika ada yang gagal, exit code 1 dan laporan detail.
"""

import importlib
import logging
import sys
import time

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


def get_critical_modules():
    """Import CRITICAL_MODULES dari main_checker_3.py"""
    try:
        # Pastikan main_checker_3.py ada di path yang sama
        import main_checker_3
        return main_checker_3.CRITICAL_MODULES
    except ImportError as e:
        print(f"❌ Gagal mengimpor main_checker_3: {e}")
        print("   Pastikan file main_checker_3.py berada di direktori yang sama.")
        sys.exit(1)
    except AttributeError:
        print("❌ CRITICAL_MODULES tidak ditemukan di main_checker_3.py.")
        sys.exit(1)


def safe_import(module_name: str) -> tuple[bool, str]:
    """Coba import modul, kembalikan (success, error_message)"""
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
    print(" 🛡️ P50 CRITICAL MODULES IMPORT SCAN 🛡️")
    print("=" * 70)
    print()

    start_time = time.monotonic()

    # Ambil daftar modul kritis
    critical_modules = get_critical_modules()
    total = len(critical_modules)
    print(f"📦 Ditemukan {total} modul kritis yang akan diperiksa.\n")

    # Variabel pelacakan
    success_count = 0
    failures = []  # list of (label, module, error)

    print("-" * 70)
    for idx, (label, module_name) in enumerate(critical_modules, 1):
        # Tampilkan progres
        print(f"[{idx:3d}/{total}] {label:40s} -> ", end="", flush=True)

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
        for label, module, err in failures:
            print(f"  ❌ {label} ({module})")
            print(f"     Error: {err}")
        print("\n❌ STATUS: GAGAL — Sistem tidak siap deploy.")
        sys.exit(1)
    else:
        print("\n🎉 STATUS: 100% SUKSES — Semua modul kritis dapat diimpor.")
        print("   Sistem siap untuk deployment.")
        sys.exit(0)


if __name__ == "__main__":
    main()
