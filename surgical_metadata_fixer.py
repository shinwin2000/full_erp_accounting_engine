#!/usr/bin/env python3
import os
import re
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent
ORM_DIR = ROOT / "infrastructure" / "persistence_orm"

# Regex untuk mendeteksi pelanggaran deklarasi kata kunci 'metadata' di ORM
ORM_PATTERN = re.compile(r"^(\s*)metadata(\s*[:=]\s*(?:Mapped\[|mapped_column\(|Column\())")

def fix_orm_models():
    print("🔍 [FASE 1] Memindai berkas ORM untuk pelanggaran kata kunci 'metadata'...")
    violation_found = False
    
    if not ORM_DIR.exists():
        print(f"❌ Folder ORM tidak ditemukan di: {ORM_DIR}")
        return
        
    for py_file in ORM_DIR.glob("*.py"):
        if py_file.name == "__init__.py":
            continue
        try:
            content = py_file.read_text(encoding="utf-8")
        except Exception as e:
            continue
            
        lines = content.splitlines()
        modified = False
        new_lines = []
        
        for idx, line in enumerate(lines):
            match = ORM_PATTERN.match(line)
            if match:
                violation_found = True
                print(f"\n🎯 PELANGGARAN DITEMUKAN di {py_file.relative_to(ROOT)} baris {idx+1}:")
                print(f"   Lama: {line.strip()}")
                
                # Injeksi nama kolom fisik database "metadata" agar skema DB tetap aman
                if "mapped_column(" in line:
                    new_line = line.replace("metadata", "payload_metadata", 1).replace("mapped_column(", 'mapped_column("metadata", ', 1)
                elif "Column(" in line:
                    new_line = line.replace("metadata", "payload_metadata", 1).replace("Column(", 'Column("metadata", ', 1)
                else:
                    new_line = line.replace("metadata", "payload_metadata", 1)
                
                print(f"   Baru: {new_line.strip()}")
                new_lines.append(new_line)
                modified = True
            else:
                new_lines.append(line)
                
        if modified:
            # Membuat backup dengan ekstensi khusus agar aman
            backup_path = py_file.with_suffix(".py.bak_reserved")
            py_file.rename(backup_path)
            py_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
            print(f"💾 BERHASIL DISEMBUHKAN & DI-BACKUP: {py_file.name} -> .py.bak_reserved")

    if not violation_found:
        print("✅ Tidak ditemukan pelanggaran deklarasi properti 'metadata' di layer ORM.")

def scan_business_logic_references():
    print("\n🔍 [FASE 2] Memindai referensi kode bisnis yang memanggil '.metadata'...")
    reference_count = 0
    # Pola untuk mencari pemanggilan atribut objek seperti event.metadata, log.metadata, dll.
    REF_PATTERN = re.compile(r"\b([a-z_][a-z0-9_]*)\.metadata\b")
    
    for path in ROOT.rglob("*.py"):
        # Lewati folder lingkungan virtual, git, cache, dan berkas backup
        if any(p in path.parts for p in (".venv", "venv", "env", ".git", "__pycache__")) or path.suffix == ".bak_reserved":
            continue
        # Lewati folder ORM yang sudah kita tangani di Fase 1
        if "infrastructure/persistence_orm" in path.as_posix():
            continue
            
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except Exception:
            continue
            
        printed_file_header = False
        for idx, line in enumerate(lines):
            if line.strip().startswith("#") or "import " in line:
                continue
                
            matches = REF_PATTERN.findall(line)
            if matches:
                # Saring kata kunci bawaan sistem yang legal agar tidak memunculkan false positive
                filtered = [m for m in matches if m not in ("self", "cls", "Base", "metadata", "db", "engine", "model", "metadata_obj")]
                if filtered:
                    if not printed_file_header:
                        print(f"\n📄 Referensi ditemukan di: {path.relative_to(ROOT)}")
                        printed_file_header = True
                    print(f"   📍 Baris {idx+1}: {line.strip()}")
                    reference_count += 1
                    
    print(f"\n✨ Pemindaian Selesai. Ditemukan {reference_count} baris kode logis yang perlu Anda sesuaikan.")

if __name__ == '__main__':
    print("🚀 MENJALANKAN SURGICAL ORM RESERVED KEYWORD FIXER...\n")
    fix_orm_models()
    scan_business_logic_references()
    print("\n💡 Langkah Selanjutnya:")
    print("1. Jika ada file di Fase 2, buka file tersebut dan ubah `.metadata` menjadi `.payload_metadata`.")
    print("2. Jalankan kembali: python main_checker.py --deep-check")