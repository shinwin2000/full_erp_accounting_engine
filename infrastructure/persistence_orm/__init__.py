# infrastructure/persistence_orm/__init__.py
"""
Package: infrastructure.persistence_orm
SQLAlchemy ORM models and tables - lazy imports to avoid circular dependencies.

============================================================================
CATATAN REFACTOR (baca ini kalau bingung kenapa file ini berubah)
============================================================================
Root cause bug "Failed to find active entities: ... failed to locate a name
('InventoryBatchTable')" yang bikin login gagal setelah restart komputer:

1. SQLAlchemy meng-configure SELURUH mapper registry secara bersamaan saat
   mapper pertama diakses (bukan cuma tabel yang dipakai query tsb). Jadi
   satu relationship() yang rusak di modul mana pun akan membuat SEMUA
   query gagal - termasuk query yang sama sekali tidak berhubungan
   (contoh: list legal entities untuk login, gagal gara-gara relationship
   di modul inventory).

2. Sebelumnya modul ini memakai daftar manual `_MODULE_NAMES` yang harus
   di-update tangan setiap kali ada file model baru. Daftar itu sudah
   TIDAK SINKRON dengan file yang benar-benar ada di folder ini - minimal
   9 file model nyata tidak pernah ikut di-import oleh load_all_models():
   approval_delegation_table, approval_matrix_table,
   capital_contribution_table, iam_permission_table, iam_role_table,
   iam_session_table, login_attempt_table, outbox_message_table,
   payroll_payslip_table.

   Karena load_all_models() menelan ImportError hanya sebagai warning
   (tidak crash), startup log tetap menampilkan "All ORM models eagerly
   loaded ✓" walau registry-nya sebenarnya belum lengkap. Kalau ada
   relationship() di file lain yang menunjuk (via string) ke class yang
   didefinisikan di salah satu dari 9 file yang "hilang" itu, mapper
   configuration akan gagal - tapi SIFATNYA TIDAK KONSISTEN, tergantung
   modul mana yang kebetulan sudah ke-import lebih dulu lewat jalur lain
   (router, repository, dsb). Inilah yang menjelaskan pola "kadang jalan,
   kadang error setelah restart".

3. Gejala spesifik 'InventoryBatchTable' di log kalian kemungkinan besar
   berasal dari file .pyc BASI di folder __pycache__ lokal (sisa dari
   sebelum class tsb di-rename menjadi InventoryFIFOLayerTable). Python
   seharusnya otomatis meng-invalidate .pyc kalau source berubah, tapi ini
   bisa gagal di Windows kalau ada tool (antivirus/OneDrive/backup) yang
   menyentuh timestamp file, atau kalau ada lebih dari satu virtualenv/
   copy project yang dipakai bergantian. Solusi cepat: hapus semua folder
   __pycache__ di project lalu jalankan ulang (lihat catatan di README /
   pesan chat).

PERBAIKAN DI FILE INI:
- _MODULE_NAMES sekarang di-generate OTOMATIS dengan men-scan seluruh file
  .py di folder ini (bukan daftar manual yang gampang basi). Setiap file
  model baru otomatis ikut ter-load tanpa perlu edit file ini lagi.
- load_all_models() sekarang memanggil sqlalchemy.orm.configure_mappers()
  di akhir, supaya relationship yang rusak KETAHUAN SAAT STARTUP dengan
  pesan error yang jelas - bukan diam-diam lolos lalu meledak nanti secara
  acak di request user (seperti kasus login di atas).
- Semua API publik lama (load_all_models, _MODULE_NAMES, lazy __getattr__)
  dipertahankan supaya kode lain yang sudah memakainya tidak perlu diubah.
============================================================================
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ============================================================================
# MODUL YANG SENGAJA DIKECUALIKAN
# ============================================================================
# Bukan model SQLAlchemy (Base/declarative class) - jangan ikut di-eager-load
# sebagai "model", walaupun tetap boleh diimpor manual seperti biasa.
_EXCLUDED_MODULE_NAMES: frozenset[str] = frozenset(
    {
        "__init__",
        "database",  # helper session factory, bukan model
        "unit_of_work",  # abstraksi UoW, bukan model
    }
)


def _discover_module_names() -> list[str]:
    """
    Scan folder package ini dan kembalikan nama semua modul .py di
    dalamnya (tanpa ekstensi), kecuali yang ada di _EXCLUDED_MODULE_NAMES.

    Menggantikan daftar manual `_MODULE_NAMES` yang sebelumnya harus
    di-update tangan setiap kali ada file model baru ditambahkan/dihapus,
    dan yang sudah terbukti tidak sinkron (lihat catatan di atas).
    """
    package_dir = Path(__file__).resolve().parent
    discovered: list[str] = []
    for module_info in pkgutil.iter_modules([str(package_dir)]):
        name = module_info.name
        if module_info.ispkg:
            continue
        if name in _EXCLUDED_MODULE_NAMES:
            continue
        discovered.append(name)
    return sorted(discovered)


# Dihitung sekali saat package pertama kali diimpor. Tetap bernama
# `_MODULE_NAMES` (dan tetap sebuah list[str]) agar kompatibel dengan kode
# lain yang mungkin sudah membaca `infrastructure.persistence_orm._MODULE_NAMES`.
_MODULE_NAMES: list[str] = _discover_module_names()


# ============================================================================
# LAZY IMPORTER
# ============================================================================
def __getattr__(name: str) -> Any:
    """Lazy import modul ORM saat atribut diakses."""
    if name in _MODULE_NAMES:
        try:
            # Impor modul di dalam package yang sama
            module = importlib.import_module(f".{name}", __package__)
            return module
        except ImportError as e:
            logger.warning(f"Failed to lazy import '{name}': {e}")
            raise AttributeError(f"module {__name__} has no attribute {name}") from e
    raise AttributeError(f"module {__name__} has no attribute {name}")


# ============================================================================
# EAGER LOADER (dipanggil sekali saat startup aplikasi)
# ============================================================================
def load_all_models(*, validate_mappers: bool = True) -> None:
    """Import semua modul ORM secara eksplisit agar seluruh class terdaftar
    di SQLAlchemy class registry sebelum mapper relationship di-resolve.
    Wajib dipanggil sekali saat startup, sebelum request pertama masuk.

    Args:
        validate_mappers: Jika True (default), langsung memanggil
            `sqlalchemy.orm.configure_mappers()` setelah semua modul
            diimpor. Ini membuat relationship yang rusak/salah nama
            (misalnya menunjuk ke class yang tidak pernah ter-import)
            GAGAL SAAT STARTUP dengan traceback yang jelas, alih-alih
            lolos diam-diam dan baru meledak nanti secara acak saat ada
            request user yang menyentuh mapper terkait - persis seperti
            kasus 'InventoryBatchTable' yang membuat halaman login gagal.
    """
    failed_modules: list[str] = []

    for name in _MODULE_NAMES:
        try:
            importlib.import_module(f".{name}", __package__)
        except ImportError as e:
            logger.warning(f"Failed to eager-load ORM module '{name}': {e}")
            failed_modules.append(name)

    if failed_modules:
        logger.warning(
            "load_all_models(): %d modul gagal diimpor dan TIDAK ikut "
            "terdaftar di SQLAlchemy registry: %s. Relationship apa pun "
            "yang menunjuk ke class di modul-modul ini akan membuat "
            "mapper configuration gagal saat pertama kali diakses.",
            len(failed_modules),
            failed_modules,
        )

    if validate_mappers:
        from sqlalchemy.orm import configure_mappers

        # Memaksa SQLAlchemy meresolusi & memvalidasi SEMUA relationship
        # di SELURUH registry sekarang juga (saat startup), bukan nanti
        # secara lazy saat request pertama masuk. Kalau ada relationship
        # yang string target class-nya tidak ditemukan (typo, rename yang
        # belum konsisten, modul yang lupa diimpor, dsb), exception akan
        # muncul DI SINI dengan pesan yang jelas menyebut mapper & nama
        # class yang bermasalah - jauh lebih mudah didiagnosis dibanding
        # error acak di endpoint yang tidak berhubungan.
        configure_mappers()
        logger.info(
            "SQLAlchemy mapper registry berhasil divalidasi (%d modul ORM dimuat) ✓",
            len(_MODULE_NAMES) - len(failed_modules),
        )


# ============================================================================
# EKSPOR (untuk memudahkan IDE dan static analysis)
# ============================================================================
__all__ = [*_MODULE_NAMES, "load_all_models"]
