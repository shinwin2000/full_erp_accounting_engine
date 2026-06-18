#!/usr/bin/env python3
"""
remove_app_container.py (Optimized & Safer Version)
1. Ganti semua prefix import 'app.container' menjadi 'bootstrap.dependency_container.ioc_container'
2. Bersihkan import 'app.container' atau 'from app import container' yang tidak terpakai (termasuk yang berindentasi)
3. Hapus file app/container.py dan app/dependencies.py dengan aman
"""

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent

def find_and_replace_imports():
    """Ganti semua bentuk import app.container secara fleksibel"""
    replaced_files = []
    
    # Mencari pola 'from app.container import ...' secara umum tanpa kaku pada 'get_container'
    from_pattern = re.compile(r'from\s+app\.container\s+import')
    import_pattern = re.compile(r'import\s+app\.container')
    
    for py_file in PROJECT_ROOT.rglob('*.py'):
        # Skip folder virtual environment dan cache
        if any(p in py_file.parts for p in ['.git', '__pycache__', '.venv', 'venv', 'env', 'node_modules', '.pytest_cache', '.mypy_cache', '.ruff_cache', 'dist', 'build']):
            continue
            
        # Jangan proses script pembantu ini sendiri
        if py_file.name == Path(__file__).name:
            continue
            
        try:
            content = py_file.read_text(encoding='utf-8')
        except UnicodeDecodeError:
            continue

        if 'app.container' in content:
            # Mengganti hanya bagian pangkal import agar fleksibel terhadap multi-line atau variasi objek
            new_content = from_pattern.sub('from bootstrap.dependency_container.ioc_container import', content)
            new_content = import_pattern.sub('import bootstrap.dependency_container.ioc_container', new_content)
            
            if new_content != content:
                py_file.write_text(new_content, encoding='utf-8')
                replaced_files.append(py_file.relative_to(PROJECT_ROOT))
                print(f"✅ Diperbarui: {py_file.relative_to(PROJECT_ROOT)}")
                
    return replaced_files

def remove_app_container_imports_from_files():
    """Hapus sisa import app.container yang tidak digunakan (Aman untuk baris berindentasi)"""
    # Menambahkan \s* di depan ^ agar mencakup import di dalam fungsi/indented blocks
    pattern = re.compile(r'^\s*import\s+app\.container\s*$\n?', re.MULTILINE)
    pattern2 = re.compile(r'^\s*from\s+app\s+import\s+container\s*$\n?', re.MULTILINE)
    
    for py_file in PROJECT_ROOT.rglob('*.py'):
        if any(p in py_file.parts for p in ['.git', '__pycache__', '.venv', 'venv', 'env', 'node_modules', '.pytest_cache', '.mypy_cache', '.ruff_cache', 'dist', 'build']):
            continue
        try:
            content = py_file.read_text(encoding='utf-8')
        except UnicodeDecodeError:
            continue
            
        new_content = pattern.sub('', content)
        new_content = pattern2.sub('', new_content)
        
        if new_content != content:
            py_file.write_text(new_content, encoding='utf-8')
            print(f"🧹 Sisa import dibersihkan: {py_file.relative_to(PROJECT_ROOT)}")

def remove_app_container_files_safely():
    """Hapus file target dengan peringatan dan konfirmasi"""
    container_py = PROJECT_ROOT / 'app' / 'container.py'
    dependencies_py = PROJECT_ROOT / 'app' / 'dependencies.py'
    removed = []
    
    for file_path in [container_py, dependencies_py]:
        if file_path.exists():
            # Opsional: Jika ingin sangat aman, ganti .unlink() dengan memindahkannya ke folder backup temporer
            file_path.unlink()
            removed.append(str(file_path.relative_to(PROJECT_ROOT)))
            print(f"🗑️  Berhasil menghapus: {file_path.relative_to(PROJECT_ROOT)}")
            
    return removed

def main():
    print("=" * 64)
    # Memastikan user sudah siap dan sudah backup kodenya via Git
    print("  MENGHILANGKAN app.container — MIGRASI KE bootstrap")
    print("=" * 64)
    print("PERINGATAN: Pastikan Anda sudah men-commit pekerjaan Anda di Git sebelum melanjutkan!\n")
    
    confirm = input("Apakah Anda ingin melanjutkan? (y/N): ").strip().lower()
    if confirm != 'y':
        print("❌ Operasi dibatalkan.")
        return

    # 1. Jalankan penggantian alamat import
    replaced = find_and_replace_imports()
    print(f"\n➔ Selesai: {len(replaced)} file disesuaikan import-nya.")

    # 2. Bersihkan baris import yang yatim/terbengkalai
    remove_app_container_imports_from_files()

    # 3. Hapus file fisik lama
    removed = remove_app_container_files_safely()
    print(f"➔ Selesai: {len(removed)} file lama dihapus.")

    print("\n" + "-" * 64)
    print(" 🚀 Sekarang jalankan: python main_checker.py --deep-check --traceback")
    print("-" * 64)

if __name__ == "__main__":
    main()