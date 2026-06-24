#!/usr/bin/env python3
"""
S+ Grade DI Container Integrity Test with Contract Validation.
Script ini tidak hanya mendaftarkan adapter dan memaksa IoC Container
menginisialisasi SEMUA instance serta mendeteksi In-Memory Fallbacks,
tetapi juga memvalidasi kontrak method untuk interface kritis
berdasarkan nama port yang benar dan metode yang diharapkan.
"""

import sys
import traceback
import logging
import asyncio
import time
from typing import Dict, List

# Aktifkan logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logging.getLogger("sqlalchemy").setLevel(logging.WARNING)

# ========== KONTRAK YANG HARUS DIPENUHI ==========
# Nama interface menggunakan nama port yang terdaftar, bukan prefiks "I"
CONTRACT_CHECKS: Dict[str, List[str]] = {
    "UnitOfWorkPort": ["commit", "rollback", "begin"],
    "CoreTaxPort": ["submit_tax", "get_status"],
    "IAMUserRepositoryPort": ["save", "find_by_username", "find_by_id"],
    "ARRepositoryPort": ["save_invoice", "find_invoice_by_id"],
    "APRepositoryPort": ["save_invoice", "find_invoice_by_id"],
    "InventoryRepositoryPort": ["save_item", "find_item_by_id", "adjust_stock"],
    "FixedAssetRepositoryPort": ["save_asset", "find_asset_by_id"],
    "PayrollRepositoryPort": ["save_payroll", "find_by_employee"],
    "ConsolidationRepositoryPort": ["save_group", "find_group"],
}

async def test_di_container():
    print("=" * 70)
    print(" 🛡️ STRICT DI CONTAINER INTEGRITY TEST + CONTRACT VALIDATION 🛡️")
    print("=" * 70)
    print()

    start_time = time.monotonic()
    has_critical_failures = False
    success_count = 0
    in_memory_detected = []
    resolution_errors = []
    contract_failures = []

    try:
        # Langkah 1: Import adapter registry dan IoC Container
        print("1. Mengimpor adapter_registry...")
        from bootstrap.dependency_container.adapter_registry import get_adapter_registry
        from bootstrap.dependency_container.ioc_container import get_container
        print("   ✅ Import berhasil.")

        # Langkah 2: Registrasi
        print("2. Menjalankan register_all()...")
        registry = get_adapter_registry()
        registry.register_all()
        print("   ✅ Semua registrasi di-trigger.")

        # Langkah 3: Mendapatkan daftar semua interface yang terdaftar
        container = get_container()
        registered_types = container.get_registered_types()
        total_types = len(registered_types)
        print(f"3. Ditemukan {total_types} dependency yang terdaftar. Memulai resolusi masal...")
        
        if total_types == 0:
            raise RuntimeError("CRITICAL: Tidak ada dependency yang terdaftar di container!")

        # Langkah 4: Resolve SEMUA adapter satu per satu & Cek Fallback & Kontrak
        print("-" * 70)
        for interface in registered_types:
            interface_name = interface.__name__ if hasattr(interface, "__name__") else str(interface)
            
            try:
                # Resolve instance (mendukung class yang butuh async instantiation)
                instance = await container.resolve_async(interface)
                instance_class_name = instance.__class__.__name__

                # DETEKSI FATAL: Cegah Silent Fallback
                if "InMemory" in instance_class_name:
                    in_memory_detected.append(f"{interface_name} -> {instance_class_name}")
                else:
                    success_count += 1
                    print(f"   ✅ OK: {interface_name} -> {instance_class_name}")

                # Validasi kontrak jika interface termasuk dalam CONTRACT_CHECKS
                if interface_name in CONTRACT_CHECKS:
                    expected_methods = CONTRACT_CHECKS[interface_name]
                    missing_methods = []
                    for method_name in expected_methods:
                        if not hasattr(instance, method_name) or not callable(getattr(instance, method_name)):
                            missing_methods.append(method_name)
                    if missing_methods:
                        contract_failures.append(
                            f"{interface_name} missing methods: {', '.join(missing_methods)}"
                        )
                        print(f"   ❌ CONTRACT FAIL: {interface_name} missing methods: {missing_methods}")
                    else:
                        print(f"   ✅ CONTRACT OK: {interface_name} has all required methods.")

            except Exception as e:
                # Kumpulkan semua error tanpa langsung berhenti (fail-fast tapi komprehensif)
                resolution_errors.append((interface_name, traceback.format_exc()))
        print("-" * 70)

        # Langkah 5: Evaluasi Hasil Akhir
        if in_memory_detected:
            has_critical_failures = True
            print("\n🚨 [CRITICAL] Ditemukan Silent In-Memory Fallback!")
            print("Adapter berikut gagal terhubung ke implementasi aslinya (SQLAlchemy/Kafka/dll):")
            for item in in_memory_detected:
                print(f"   ❌ {item}")

        if resolution_errors:
            has_critical_failures = True
            print("\n🚨 [CRITICAL] Gagal melakukan resolve (instansiasi) pada dependency berikut:")
            for interface_name, trace in resolution_errors:
                print("*" * 60)
                print(f"FAILED TO RESOLVE: {interface_name}")
                print(trace)
                print("*" * 60)

        if contract_failures:
            has_critical_failures = True
            print("\n🚨 [CRITICAL] Kontrak method tidak terpenuhi untuk interface berikut:")
            for fail in contract_failures:
                print(f"   ❌ {fail}")

        # Ringkasan
        print("\n" + "=" * 70)
        print(f"Total dependency terdaftar: {total_types}")
        print(f"Berhasil di-resolve (non-InMemory): {success_count}")
        print(f"In-Memory fallback terdeteksi: {len(in_memory_detected)}")
        print(f"Resolution errors: {len(resolution_errors)}")
        print(f"Contract failures: {len(contract_failures)}")
        print("=" * 70)

        duration = time.monotonic() - start_time
        print(f"Durasi: {duration:.2f} detik")

        if has_critical_failures:
            print("\n❌ STATUS: DI Container GAGAL validasi S+ Grade.")
            sys.exit(1)
        else:
            print(f"\n🎉 STATUS: 100% SUCCESS. Seluruh {success_count} adapter berhasil di-resolve dan kontrak valid!")
            print("DI Container dijamin bersih dari in-memory fallbacks dan broken constructor.")
            sys.exit(0)

    except Exception as e:
        print("\n❌ FATAL ERROR DILUAR RESOLUSI DI CONTAINER:")
        traceback.print_exc()
        sys.exit(1)

def main():
    asyncio.run(test_di_container())

if __name__ == "__main__":
    main()