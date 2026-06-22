#!/usr/bin/env python3
"""
Pre-flight System Health Checker
Script ini memvalidasi seluruh struktur aplikasi ERP untuk menemukan Syntax Error 
dan masalah Import/Wiring sebelum aplikasi utama dijalankan.
Sudah dilengkapi toleransi encoding untuk file Windows-1252.
"""

import os
import ast
import importlib
import sys
import traceback

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

# Layer krusial yang wajib diuji coba proses import-nya
CRITICAL_LAYERS_TO_IMPORT = [
    "ports",
    "adapters",
    "domain",
    "application",
    "infrastructure",
    "bootstrap"
]

def check_syntax_all_files() -> list[str]:
    """Fase 1: Mengecek syntax seluruh file .py di dalam proyek tanpa mengeksekusinya."""
    print("="*60)
    print("🔍 FASE 1: MEMERIKSA SYNTAX SELURUH FILE PYTHON 🔍")
    print("="*60)
    
    errors = []
    scanned_count = 0
    
    for root, _, files in os.walk(PROJECT_ROOT):
        # Abaikan virtual environment atau folder cache
        if "venv" in root or "__pycache__" in root or ".git" in root:
            continue
            
        for file in files:
            if file.endswith(".py"):
                file_path = os.path.join(root, file)
                scanned_count += 1
                
                try:
                    # Percobaan pertama: Gunakan standar UTF-8
                    with open(file_path, "r", encoding="utf-8") as f:
                        source = f.read()
                    ast.parse(source)
                except UnicodeDecodeError:
                    try:
                        # Fallback: Gunakan encoding Windows (cp1252)
                        with open(file_path, "r", encoding="cp1252") as f:
                            source = f.read()
                        ast.parse(source)
                        # Beri peringatan agar kita tahu file mana yang bukan UTF-8
                        print(f"⚠️ [WARNING ENCODING] {file_path} menggunakan cp1252, bukan UTF-8.")
                    except SyntaxError as e:
                        errors.append(f"❌ [SYNTAX ERROR] {file_path}\n    Baris {e.lineno}: {e.text.strip() if e.text else ''}")
                    except Exception as e:
                        errors.append(f"❌ [READ ERROR] Gagal membaca {file_path} dengan fallback: {e}")
                except SyntaxError as e:
                    errors.append(f"❌ [SYNTAX ERROR] {file_path}\n    Baris {e.lineno}: {e.text.strip() if e.text else ''}")
                except Exception as e:
                    errors.append(f"❌ [READ ERROR] Gagal membaca {file_path}: {e}")

    print(f"✅ Selesai memindai {scanned_count} file.")
    return errors

def check_critical_imports() -> list[str]:
    """Fase 2: Memastikan module di layer krusial bisa di-import tanpa error."""
    print("\n" + "="*60)
    print("🔍 FASE 2: MEMERIKSA IMPORT PADA LAYER KRUSIAL 🔍")
    print("="*60)
    
    errors = []
    scanned_count = 0

    for root, _, files in os.walk(PROJECT_ROOT):
        # Hanya fokus pada layer yang didefinisikan
        if not any(layer in root for layer in CRITICAL_LAYERS_TO_IMPORT):
            continue
        if "venv" in root or "__pycache__" in root or ".git" in root or "tests" in root:
            continue
            
        for file in files:
            if file.endswith(".py") and file != "__init__.py":
                scanned_count += 1
                file_path = os.path.join(root, file)
                
                # Mengubah path Windows (E:\...\folder\file.py) menjadi format module Python (folder.file)
                rel_path = os.path.relpath(file_path, PROJECT_ROOT)
                module_name = rel_path.replace(os.sep, ".")[:-3] 
                
                try:
                    # Mencoba import module untuk mendeteksi ModuleNotFoundError / Circular Import
                    importlib.import_module(module_name)
                except Exception as e:
                    errors.append(f"❌ [IMPORT ERROR] Gagal memuat module '{module_name}'\n    Penyebab: {type(e).__name__} - {e}")

    print(f"✅ Selesai mencoba import {scanned_count} module krusial.")
    return errors

def main():
    # Pastikan direktori proyek masuk dalam system path agar import berjalan lancar
    if PROJECT_ROOT not in sys.path:
        sys.path.insert(0, PROJECT_ROOT)

    syntax_errors = check_syntax_all_files()
    import_errors = check_critical_imports()
    
    all_errors = syntax_errors + import_errors
    
    print("\n" + "="*60)
    print("📊 LAPORAN KESEHATAN SISTEM")
    print("="*60)
    
    if all_errors:
        print(f"🚨 DITEMUKAN {len(all_errors)} MASALAH YANG HARUS DIPERBAIKI SEBELUM RUNTIME 🚨\n")
        for err in all_errors:
            print(err)
            print("-" * 60)
        sys.exit(1)
    else:
        print("🎉 SISTEM ROBUST! Tidak ditemukan error syntax atau masalah import krusial.")
        print("🚀 Anda siap untuk menjalankan aplikasi utama.")
        sys.exit(0)

if __name__ == "__main__":
    main()