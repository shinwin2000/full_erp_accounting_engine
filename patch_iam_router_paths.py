"""
Patch: hapus prefix "/iam" yang hardcode di dalam path endpoint
fastapi_iam_router.py. Router ini sudah didaftarkan dengan prefix
"/api/v1/iam" di main.py, jadi path di dalam file tidak boleh
mengulang "/iam" lagi -- itu menyebabkan path akhir jadi
"/api/v1/iam/iam/..." (404).

Cara pakai:
    cd E:\\full_erp_accounting_engine
    python patch_iam_router_paths.py
"""
import re
from pathlib import Path

TARGET = Path("adapters/primary_api/v1/fastapi_iam_router.py")

# Cocokkan baris yang isinya HANYA path string route, misal:
#     "/iam/users",
#     "/iam/users/{user_id}",
#     "/iam/sessions"
# (dengan atau tanpa koma di akhir)
PATTERN = re.compile(r'^(\s*)"(/iam)((?:/[^"]*)?)"(,?)\s*$', re.MULTILINE)


def main() -> None:
    text = TARGET.read_text(encoding="utf-8")

    matches = list(PATTERN.finditer(text))
    print(f"Ditemukan {len(matches)} baris path dengan prefix '/iam' berlebih.")

    def replacer(m: re.Match) -> str:
        indent, _prefix, rest, comma = m.groups()
        new_path = rest if rest else "/"
        return f'{indent}"{new_path}"{comma}'

    new_text, count = PATTERN.subn(replacer, text)
    print(f"Diperbaiki {count} baris.")

    TARGET.write_text(new_text, encoding="utf-8")
    print("Selesai. File tersimpan:", TARGET)


if __name__ == "__main__":
    main()
