import os
import re
import shutil

# ==========================================
# PENGATURAN KEAMANAN (SILAKAN DISESUAIKAN)
# ==========================================
# Ubah menjadi False HANYA jika Anda sudah melihat hasil Dry Run dan merasa yakin.
DRY_RUN = False

# Akan membuat salinan ".bak" untuk setiap file yang dimodifikasi.
CREATE_BACKUP = True 

# HANYA izinkan folder dan file root tertentu (layer HTTP)
ALLOWED_FOLDERS = ['app', 'adapters', 'bootstrap']
ALLOWED_ROOT_FILES = ['asgi.py']

# ==========================================
# REGEX PATTERNS
# ==========================================
# Memastikan "Request" digunakan sebagai tipe (contoh: "request: Request" atau "req:Request")
USAGE_PATTERN = re.compile(r':\s*Request\b')

# Memastikan belum ada import FastAPI/Starlette untuk Request
IMPORT_PATTERN = re.compile(r'^from\s+(fastapi|starlette\.requests)\s+import\s+.*?\bRequest\b', re.MULTILINE)


def is_allowed_path(filepath):
    """Mengecek apakah path file diizinkan untuk dimodifikasi."""
    normalized_path = os.path.normpath(filepath)
    parts = normalized_path.split(os.sep)
    
    # Cek file di root
    if len(parts) == 1 and parts[0] in ALLOWED_ROOT_FILES:
        return True
    
    # Cek folder
    if len(parts) > 1 and parts[0] in ALLOWED_FOLDERS:
        return True
        
    return False

def find_safe_insert_index(lines):
    """Mencari baris yang aman untuk menaruh import (di bawah Shebang dan Docstring)."""
    in_docstring = False
    
    for i, line in enumerate(lines):
        stripped = line.strip()
        
        # Abaikan Shebang di baris 1
        if i == 0 and line.startswith('#!'):
            continue
            
        # Logika Docstring (Kutipan 3)
        if stripped.startswith('"""') or stripped.startswith("'''"):
            if not in_docstring:
                in_docstring = True
                # Jika docstring selesai di baris yang sama
                if (stripped.endswith('"""') or stripped.endswith("'''")) and len(stripped) > 3:
                    in_docstring = False
            else:
                in_docstring = False
            continue
            
        if in_docstring:
            continue
            
        # Jika ketemu baris kode yang valid atau import lain, kita berhenti di sini
        if stripped and not stripped.startswith('#'):
            return i
            
    return 0

def process_file(filepath):
    # Hanya proses file yang diizinkan
    if not is_allowed_path(filepath):
        return

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except UnicodeDecodeError:
        print(f"[ERROR] Gagal membaca {filepath} (Bukan UTF-8). Dilewati.")
        return

    # 1. Pastikan file menggunakan "Request" sebagai tipe data
    if not USAGE_PATTERN.search(content):
        return

    # 2. Pastikan file belum meng-import "Request"
    if IMPORT_PATTERN.search(content):
        return

    # Jika lolos kedua cek, file ini BUTUH import FastAPI
    if DRY_RUN:
        print(f"[DRY RUN] Akan menambahkan import pada: {filepath}")
        return

    # --- PROSES MODIFIKASI REAL (JIKA DRY_RUN = False) ---
    
    if CREATE_BACKUP:
        backup_path = filepath + ".bak"
        shutil.copy2(filepath, backup_path)
        print(f"[INFO] Backup dibuat: {backup_path}")

    lines = content.split('\n')
    insert_idx = find_safe_insert_index(lines)
    
    # Sisipkan import
    lines.insert(insert_idx, "from fastapi import Request")
    
    # Simpan kembali dengan aman
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
        
    print(f"[BERHASIL] Import ditambahkan ke: {filepath}")

def main():
    print(f"=== Memulai Scan (DRY_RUN={DRY_RUN}) ===")
    base_dir = "."
    
    # Berjalan menyusuri proyek
    for root, _, files in os.walk(base_dir):
        # Hindari folder .git, __pycache__, dll
        if '.git' in root or '__pycache__' in root or 'venv' in root or '.venv' in root:
            continue
            
        for file in files:
            if file.endswith(".py"):
                # Dapatkan path relatif
                filepath = os.path.relpath(os.path.join(root, file), base_dir)
                process_file(filepath)
                
    print("=== Proses Selesai ===")
    if DRY_RUN:
        print("\n* Catatan: Ini hanya simulasi. Tidak ada file yang benar-benar diubah.")
        print("* Jika daftar file di atas sudah benar, ubah 'DRY_RUN = False' di dalam skrip, lalu jalankan lagi.")

if __name__ == "__main__":
    main()