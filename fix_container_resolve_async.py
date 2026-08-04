#!/usr/bin/env python3
"""
fix_container_resolve_async.py

Memperbaiki pola bug sistemik: banyak dependency-provider function di
adapters/primary_api/v1/*.py memanggil `container.resolve(X)` (versi
SYNC) di dalam endpoint FastAPI async, yang menyebabkan:

    RuntimeError: Cannot resolve <class 'X'> synchronously inside
    running event loop. Use await resolve_async() instead.

Script ini untuk tiap file target:
  1. Membuat backup <file>.py.bak (kalau belum ada) sebelum mengubah apa pun.
  2. Mencari baris yang mengandung `container.resolve(...)` TANPA
     `resolve_async` (return atau assignment biasa).
  3. Mengganti jadi `await container.resolve_async(...)`.
  4. Menelusuri ke atas untuk menemukan `def` fungsi pembungkusnya dan
     memastikan fungsi itu `async def` (menambahkan `async` kalau
     fungsi itu masih `def` biasa).

Cara pakai:
    cd E:\\full_erp_accounting_engine
    python fix_container_resolve_async.py            # jalankan perbaikan
    python fix_container_resolve_async.py --dry-run   # preview saja, tidak menulis apa pun

Setelah dijalankan, cek hasilnya dengan:
    python -m py_compile adapters\\primary_api\\v1\\*.py
(atau compile satu-satu kalau wildcard tidak jalan di PowerShell)

Kalau ada yang salah / mau balikin ke semula:
    tinggal copy isi <file>.py.bak menimpa <file>.py lagi.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Daftar file yang diketahui punya pola container.resolve() sync,
# hasil dari:
#   Get-ChildItem ... | Select-String -Pattern "container\.resolve\(" |
#       Where-Object { $_.Line -notmatch "resolve_async" }
TARGET_FILES = [
    "fastapi_ap_router.py",
    "fastapi_approval_router.py",
    "fastapi_ar_router.py",
    "fastapi_audit_router.py",
    "fastapi_bank_cash_router.py",
    "fastapi_budget_router.py",
    "fastapi_coa_router.py",
    "fastapi_consolidation_router.py",
    "fastapi_currency_exchange_router.py",
    "fastapi_document_router.py",
    "fastapi_fixed_asset_router.py",
    "fastapi_forex_router.py",
    "fastapi_goodwill_router.py",
    "fastapi_hedge_router.py",
    "fastapi_intangible_asset_router.py",
    "fastapi_inventory_router.py",
    "fastapi_journal_router.py",
    "fastapi_ledger_router.py",
    "fastapi_maintenance_router.py",
    "fastapi_manufacturing_router.py",
    "fastapi_project_router.py",
    "fastapi_purchase_sales_router.py",
    "fastapi_report_router.py",
    "fastapi_system_settings_router.py",
    "fastapi_tax_coretax_router.py",
    "fastapi_umkm_router.py",
]

ROUTER_DIR = Path("adapters") / "primary_api" / "v1"

DEF_RE = re.compile(r"^(\s*)(async\s+)?def\s+(\w+)\s*\(")
# Cocokkan: `return container.resolve(X)` atau `foo = container.resolve(X)`
RESOLVE_RE = re.compile(
    r"^(\s*)(return\s+|(\w+)\s*=\s*)?container\.resolve\((.*)\)(\s*)$"
)


def read_text_flexible(path: Path) -> tuple[str, str]:
    """Baca file dengan fallback encoding. Kembalikan (isi, encoding_yang_dipakai).

    Beberapa file di proyek ini ternyata tidak murni UTF-8 (mis. ada
    karakter em-dash atau simbol lain tersimpan sebagai Windows-1252).
    Coba beberapa encoding umum sebelum menyerah.
    """
    raw = path.read_bytes()
    for enc in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    # Fallback terakhir: latin-1 tidak pernah gagal decode (1 byte = 1 char)
    return raw.decode("latin-1", errors="replace"), "latin-1"


def fix_file(path: Path, dry_run: bool = False) -> int:
    """Kembalikan jumlah baris yang diubah di file ini."""
    original_text, source_encoding = read_text_flexible(path)
    lines = original_text.split("\n")

    last_def_idx: int | None = None
    def_needs_async: set[int] = set()
    n_changed = 0

    for i, line in enumerate(lines):
        dm = DEF_RE.match(line)
        if dm:
            last_def_idx = i

        if "resolve_async" in line:
            continue

        rm = RESOLVE_RE.match(line)
        if not rm:
            continue

        indent, prefix, assign_var, arg, trailing = rm.groups()
        prefix = prefix or ""

        if prefix.strip() == "return":
            new_line = f"{indent}return await container.resolve_async({arg}){trailing}"
        elif assign_var:
            new_line = f"{indent}{assign_var} = await container.resolve_async({arg}){trailing}"
        else:
            # container.resolve(X) berdiri sendiri tanpa return/assign
            new_line = f"{indent}await container.resolve_async({arg}){trailing}"

        if new_line != line:
            lines[i] = new_line
            n_changed += 1
            if last_def_idx is not None:
                def_needs_async.add(last_def_idx)

    for idx in def_needs_async:
        dm = DEF_RE.match(lines[idx])
        if dm and not dm.group(2):  # belum ada "async "
            lines[idx] = re.sub(r"^(\s*)def\s", r"\1async def ", lines[idx])

    if n_changed == 0:
        return 0

    new_text = "\n".join(lines)

    if dry_run:
        note = f" (encoding: {source_encoding})" if source_encoding != "utf-8" else ""
        print(f"[DRY-RUN] {path}: {n_changed} baris akan diubah{note}")
        return n_changed

    backup_path = path.with_suffix(path.suffix + ".bak")
    if not backup_path.exists():
        # Backup disimpan sebagai byte mentah asli, tidak lewat re-encode,
        # supaya 100% identik dengan file asli sebelum diubah.
        backup_path.write_bytes(path.read_bytes())

    # Tulis balik pakai encoding yang sama seperti saat dibaca, supaya
    # karakter non-ASCII asli (mis. em-dash di komentar) tidak berubah
    # jadi mojibake.
    path.write_text(new_text, encoding=source_encoding)
    note = f" (encoding: {source_encoding})" if source_encoding != "utf-8" else ""
    print(f"[FIXED] {path}: {n_changed} baris diubah (backup: {backup_path.name}){note}")
    return n_changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="Preview perubahan tanpa menulis file"
    )
    parser.add_argument(
        "--root",
        default=".",
        help="Root proyek (default: direktori saat ini). Jalankan dari E:\\full_erp_accounting_engine",
    )
    args = parser.parse_args()

    root = Path(args.root)
    router_dir = root / ROUTER_DIR

    if not router_dir.exists():
        print(f"ERROR: folder tidak ditemukan: {router_dir}", file=sys.stderr)
        print(
            "Jalankan script ini dari root proyek (E:\\full_erp_accounting_engine), "
            "atau pakai --root <path>.",
            file=sys.stderr,
        )
        return 1

    total_files_changed = 0
    total_lines_changed = 0

    for filename in TARGET_FILES:
        path = router_dir / filename
        if not path.exists():
            print(f"[SKIP] {path} tidak ditemukan")
            continue
        n = fix_file(path, dry_run=args.dry_run)
        if n > 0:
            total_files_changed += 1
            total_lines_changed += n

    print()
    print(f"Selesai. {total_files_changed} file, {total_lines_changed} baris diubah.")
    if args.dry_run:
        print("(Ini masih dry-run — jalankan tanpa --dry-run untuk benar-benar menulis.)")
    else:
        print("Backup asli tersimpan sebagai <file>.py.bak di folder yang sama.")
        print()
        print("Langkah selanjutnya — verifikasi compile:")
        print(
            r'  Get-ChildItem "adapters\primary_api\v1\*.py" | ForEach-Object { '
            r'python -m py_compile $_.FullName }'
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
