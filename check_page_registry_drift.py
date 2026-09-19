#!/usr/bin/env python3
"""
scripts/check_page_registry_drift.py
=====================================
Mengecek bahwa COLUMNS / FORM_FIELDS / ACTIONS di setiap
ui/pages/<key>_page.py (untuk modul dengan custom_page=False) SAMA
dengan definisi di registry/module_registry.py (sumber kebenaran).

Ini dibuat setelah ditemukan bug di modul Legal Entity: kolom tabel di
legal_entities_page.py sempat beda dari registry.py tanpa ada yang
sadar, karena "skrip regenerasi otomatis" yang disebut di komentar
banyak file ui/pages/*.py TERNYATA TIDAK ADA di repo ini (baru
disadari saat audit ini - lihat juga catatan yang sama di
suppliers_page.py: "tidak ada skrip regenerasi otomatis di repo ini").

DENGAN SENGAJA skrip ini HANYA MEMBANDINGKAN, tidak menimpa file secara
otomatis. Beberapa halaman (mis. suppliers_page.py) punya kode Python
tambahan di luar blok COLUMNS/FORM_FIELDS/ACTIONS/CONFIG (mis. logika
auto-generate kode saat tombol "+ Baru" diklik) yang akan HILANG kalau
filenya di-generate ulang penuh secara otomatis. Jadi kalau ada drift,
developer yang menyalin ulang bagian yang beda secara manual dari
registry.py ke file halamannya, lalu jalankan skrip ini lagi untuk
verifikasi.

Cara pakai (dari root project, tempat folder erp_frontend/ berada):
    python scripts/check_page_registry_drift.py

Exit code 0 = semua sinkron.
Exit code 1 = ada drift atau file yang tidak bisa diperiksa (lihat detail).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


def _find_repo_root(start: Path) -> Path:
    """Cari folder yang punya subfolder 'erp_frontend', mulai dari lokasi
    skrip ini lalu naik ke folder induk. Dibuat begini (bukan asumsi kaku
    'skrip ada di <root>/scripts/') supaya tidak error kalau skrip ini
    ditaruh langsung di root project atau di folder lain."""
    candidate = start
    for _ in range(5):
        if (candidate / "erp_frontend").is_dir():
            return candidate
        if candidate.parent == candidate:
            break
        candidate = candidate.parent
    raise SystemExit(
        f"Tidak ketemu folder 'erp_frontend' mulai dari {start} ke atas. "
        f"Jalankan skrip ini dari dalam project (mis. E:\\full_erp_accounting_engine), "
        f"atau taruh skrip ini di root project / di root/scripts/."
    )


REPO_ROOT = _find_repo_root(Path(__file__).resolve().parent)
PAGES_DIR = REPO_ROOT / "erp_frontend" / "ui" / "pages"

# ui/pages/*.py melakukan `from registry.module_registry import ...` dan
# `from core...` / `from ui...` dengan asumsi erp_frontend/ ada di sys.path
# (begitu juga cara app sungguhan dijalankan - lihat erp_frontend/main.py).
sys.path.insert(0, str(REPO_ROOT / "erp_frontend"))

import registry.module_registry as _registry_module  # noqa: E402
from registry.module_registry import MODULES, ModuleConfig  # noqa: E402

# Beberapa halaman (mis. umm_page.py) mengimpor konstanta tambahan dari
# registry.py sendiri (mis. UMKM_ACCOUNT_CHOICES) selain FieldSpec/
# FieldType/ActionSpec/ModuleConfig. Supaya blok deklaratifnya bisa
# di-exec tanpa "NameError", namespace awal diisi SEMUA nama publik yang
# ada di module registry.py itu sendiri, bukan cuma 4 nama inti.
_BASE_NAMESPACE = {
    name: value for name, value in vars(_registry_module).items()
    if not name.startswith("_")
}


def _extract_declarative_block(source: str) -> str | None:
    """Ambil teks dari 'COLUMNS = [' sampai akhir 'CONFIG = ModuleConfig(...)'
    SAJA - tanpa import PySide6/Qt atau kelas kustom di bawahnya - supaya
    bisa di-exec tanpa perlu PySide6 ter-install dan tanpa menjalankan kode
    UI apa pun."""
    start_match = re.search(r"^COLUMNS\s*=", source, re.MULTILINE)
    config_match = re.search(r"^CONFIG\s*=\s*ModuleConfig\(", source, re.MULTILINE)
    if not start_match or not config_match:
        return None

    depth = 0
    end = None
    for j in range(config_match.end() - 1, len(source)):
        if source[j] == "(":
            depth += 1
        elif source[j] == ")":
            depth -= 1
            if depth == 0:
                end = j + 1
                break
    if end is None:
        return None
    return source[start_match.start():end]


def _load_page_config(page_path: Path) -> ModuleConfig | None:
    source = page_path.read_text(encoding="utf-8")
    block = _extract_declarative_block(source)
    if block is None:
        return None
    namespace = dict(_BASE_NAMESPACE)
    exec(compile(block, str(page_path), "exec"), namespace)  # noqa: S102
    return namespace.get("CONFIG")


def main() -> int:
    drift_found = False
    checked = 0

    for key, cfg in sorted(MODULES.items()):
        if cfg.custom_page:
            continue

        page_path = PAGES_DIR / f"{key}_page.py"
        if not page_path.exists():
            print(f"[SKIP] {key}: tidak ada {page_path.relative_to(REPO_ROOT)} "
                  f"(modul baru belum ada UI generiknya, atau seharusnya custom_page=True)")
            continue

        source = page_path.read_text(encoding="utf-8")
        if re.search(rf'^CONFIG\s*=\s*MODULES\[\s*["\']{re.escape(key)}["\']\s*\]', source, re.MULTILINE):
            # Pola terbaik: halaman langsung mengambil CONFIG dari
            # registry.py (mis. customers_page.py: `CONFIG = MODULES["customers"]`)
            # alih-alih menyalin ulang COLUMNS/FORM_FIELDS/dst. Drift jadi
            # mustahil karena cuma ada SATU definisi - anggap otomatis sinkron.
            checked += 1
            continue

        page_cfg = None
        parse_error = None
        try:
            page_cfg = _load_page_config(page_path)
        except Exception as exc:  # noqa: BLE001 - file lain punya konstanta/import
            # tambahan (mis. UMKM_ACCOUNT_CHOICES di umkm_page.py) yang tidak
            # bisa dievaluasi tanpa import penuh file tsb; laporkan sebagai
            # WARN untuk dicek manual alih-alih menghentikan seluruh skrip.
            parse_error = exc

        if page_cfg is None:
            drift_found = True
            reason = f"error: {parse_error}" if parse_error else "format menyimpang dari template biasa"
            print(f"[WARN] {key}: tidak bisa parsing blok COLUMNS/CONFIG di {page_path.name} ({reason}) - cek manual\n")
            continue

        checked += 1
        diffs = []
        if page_cfg.columns != cfg.columns:
            diffs.append(
                f"  columns:\n"
                f"    registry.py : {cfg.columns}\n"
                f"    {page_path.name}: {page_cfg.columns}"
            )

        reg_fields = [f.name for f in cfg.form_fields]
        page_fields = [f.name for f in page_cfg.form_fields]
        if reg_fields != page_fields:
            diffs.append(
                f"  form_fields (nama & urutan):\n"
                f"    registry.py : {reg_fields}\n"
                f"    {page_path.name}: {page_fields}"
            )

        reg_actions = [a.name for a in cfg.actions]
        page_actions = [a.name for a in page_cfg.actions]
        if reg_actions != page_actions:
            diffs.append(
                f"  actions:\n"
                f"    registry.py : {reg_actions}\n"
                f"    {page_path.name}: {page_actions}"
            )

        if diffs:
            drift_found = True
            print(f"[DRIFT] {key} ({page_path.name}):")
            print("\n".join(diffs))
            print()

    print(f"--- {checked} halaman generik diperiksa ---")
    if not drift_found:
        print("OK: semua halaman generik sinkron dengan registry/module_registry.py")
        return 0

    print(
        "Ada modul yang drift dari registry.py. Salin ulang COLUMNS/FORM_FIELDS/ACTIONS\n"
        "yang berbeda dari registry.py ke file halaman terkait secara manual (JANGAN timpa\n"
        "seluruh file - beberapa halaman punya kode kustom tambahan), lalu jalankan skrip\n"
        "ini lagi untuk memastikan sudah sinkron."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
