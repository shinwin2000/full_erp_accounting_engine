#!/usr/bin/env python3
"""
tools/generate_state_transition_tests.py
==========================================
Generator test untuk state-machine di domain layer.

MASALAH YANG DISELESAIKAN
--------------------------
Checker forensik menemukan 650 titik status-transition di domain layer yang
0% ditest (confirmed). Menulis 650 test manual satu-satu tidak realistis dan
rawan salah ketik aturan transisi (dua kali salin seperti kasus
`JournalStateMachine` yang punya DUA implementasi terpisah di
domain/journal/journal_entity.py dan domain/journal/state_machine.py — lihat
CATATAN di bawah).

CARA KERJA (bukan tebak-tebakan / template kosong)
----------------------------------------------------
1. Scan domain/**/*.py cari pola: class Enum bernama "*Status" yang punya
   method `can_transition` (classmethod di Enum itu sendiri) ATAU
   `can_transition_to` (instance method) ATAU class terpisah "*StateMachine"
   dengan staticmethod `can_transition(from, to)`.
2. Untuk setiap pola yang ditemukan, modul di-IMPORT SUNGGUHAN (bukan parse
   AST/tebak), lalu fungsi transisi ASLI dipanggil untuk SETIAP pasangan
   (from_status, to_status) di seluruh anggota enum -> menghasilkan matriks
   kebenaran yang 100% akurat sesuai kode saat ini.
3. Matriks itu di-tulis eksplisit sebagai literal Python ke file test yang
   di-generate (bukan dipanggil ulang secara dinamis saat test jalan) supaya
   hasilnya jadi SNAPSHOT yang bisa dibaca manusia dan mendeteksi regresi.
4. File yang sudah ada TIDAK ditimpa tanpa --force, supaya kalau Anda sudah
   mengedit hasil generate secara manual, generator tidak menghapusnya.

CARA PAKAI
----------
    python tools/generate_state_transition_tests.py                # scan semua, generate yang belum ada
    python tools/generate_state_transition_tests.py --dry-run       # cuma tampilkan apa yang akan digenerate
    python tools/generate_state_transition_tests.py --only journal  # cuma modul yang mengandung 'journal'
    python tools/generate_state_transition_tests.py --force         # timpa file yang sudah ada

CATATAN TEMUAN SAMPINGAN (harus ditindaklanjuti manual, TIDAK di-auto-fix)
---------------------------------------------------------------------------
`domain/journal/journal_entity.py` dan `domain/journal/state_machine.py`
SAMA-SAMA mendefinisikan class `JournalStateMachine` dengan
`_ALLOWED_TRANSITIONS` sendiri-sendiri. Saat ini isinya identik, tapi ini
adalah dual-source-of-truth: kalau salah satu diedit dan yang lain tidak,
sistem akan punya dua aturan approval yang berbeda tergantung mana yang
di-import oleh caller. Generator ini akan menggenerate test terpisah untuk
KEDUA file supaya perbedaan itu langsung ketahuan di CI kalau terjadi.
Rekomendasi: konsolidasikan ke satu module dan jadikan yang lain re-export.
"""

from __future__ import annotations

import argparse
import ast
import importlib
import importlib.util
import pathlib
import sys
from dataclasses import dataclass

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOMAIN_DIR = ROOT / "domain"
OUTPUT_ROOT = ROOT / "tests" / "domain"


@dataclass
class DiscoveredStateMachine:
    module_path: str          # dotted import path, e.g. "domain.bank_cash.bank_transfer_entity"
    file_rel: str
    status_enum_name: str
    transition_owner: str     # name of the class/enum that exposes the callable
    call_style: str           # "enum_classmethod" | "instance_method" | "external_staticmethod"


def _dotted(rel_posix: str) -> str:
    p = rel_posix[:-3] if rel_posix.endswith(".py") else rel_posix
    if p.endswith("/__init__"):
        p = p[: -len("/__init__")]
    return p.replace("/", ".")


def discover(only_filter: str | None) -> list[DiscoveredStateMachine]:
    found: list[DiscoveredStateMachine] = []
    for py_file in sorted(DOMAIN_DIR.rglob("*.py")):
        if "__pycache__" in py_file.parts:
            continue
        rel = py_file.relative_to(ROOT).as_posix()
        if only_filter and only_filter not in rel:
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue

        enum_classes: dict[str, ast.ClassDef] = {}
        other_classes: dict[str, ast.ClassDef] = {}
        for node in ast.iter_child_nodes(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            base_names = [b.id for b in node.bases if isinstance(b, ast.Name)]
            if "Enum" in base_names and node.name.endswith("Status"):
                enum_classes[node.name] = node
            else:
                other_classes[node.name] = node

        for enum_name, enum_node in enum_classes.items():
            method_names = {
                n.name for n in enum_node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            if "can_transition" in method_names:
                found.append(DiscoveredStateMachine(
                    module_path=_dotted(rel), file_rel=rel, status_enum_name=enum_name,
                    transition_owner=enum_name, call_style="enum_classmethod",
                ))
            elif "can_transition_to" in method_names:
                found.append(DiscoveredStateMachine(
                    module_path=_dotted(rel), file_rel=rel, status_enum_name=enum_name,
                    transition_owner=enum_name, call_style="instance_method",
                ))

        # external "*StateMachine" class with a can_transition(from, to) staticmethod
        for cls_name, cls_node in other_classes.items():
            if not cls_name.endswith("StateMachine"):
                continue
            method_names = {
                n.name for n in cls_node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            if "can_transition" not in method_names:
                continue
            # find which *Status enum this state machine operates on by checking
            # the annotation of its can_transition method's first argument
            target_enum = None
            for n in cls_node.body:
                if isinstance(n, ast.FunctionDef) and n.name == "can_transition":
                    for arg in n.args.args:
                        if (
                            arg.annotation is not None
                            and isinstance(arg.annotation, ast.Name)
                            and arg.annotation.id.endswith("Status")
                            and arg.annotation.id in enum_classes
                        ):
                            target_enum = arg.annotation.id
                            break
            if target_enum:
                found.append(DiscoveredStateMachine(
                    module_path=_dotted(rel), file_rel=rel, status_enum_name=target_enum,
                    transition_owner=cls_name, call_style="external_staticmethod",
                ))
    return found


def _import_module(dotted: str):
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    return importlib.import_module(dotted)


def _make_enum_classmethod(enum_cls, a, b):
    return enum_cls.can_transition(a, b)


def _make_instance_method(a, b):
    return a.can_transition_to(b)


def _make_external_staticmethod(owner, a, b):
    return owner.can_transition(a, b)


def build_matrix(dsm: DiscoveredStateMachine) -> tuple[list[str], dict[tuple[str, str], bool]] | None:
    """Import modul asli dan eksekusi fungsi transisi asli untuk seluruh
    pasangan status. Return None kalau modul gagal di-import (mis. karena
    dependency infra yang berat) — dilaporkan sebagai skip, bukan dipaksakan."""
    try:
        mod = _import_module(dsm.module_path)
    except Exception as e:  # pragma: no cover - environment dependent
        print(f"  ⚠️  SKIP {dsm.file_rel}: gagal import ({type(e).__name__}: {e})")
        return None

    enum_cls = getattr(mod, dsm.status_enum_name, None)
    if enum_cls is None:
        print(f"  ⚠️  SKIP {dsm.file_rel}: enum {dsm.status_enum_name} tidak ditemukan setelah import")
        return None
    members = list(enum_cls)
    member_names = [m.name for m in members]

    if dsm.call_style == "enum_classmethod":
        def fn(a, b):
            return _make_enum_classmethod(enum_cls, a, b)
    elif dsm.call_style == "instance_method":
        def fn(a, b):
            return _make_instance_method(a, b)
    else:
        owner = getattr(mod, dsm.transition_owner, None)
        if owner is None:
            print(f"  ⚠️  SKIP {dsm.file_rel}: {dsm.transition_owner} tidak ditemukan setelah import")
            return None
        def fn(a, b):
            return _make_external_staticmethod(owner, a, b)

    matrix: dict[tuple[str, str], bool] = {}
    for a in members:
        for b in members:
            try:
                matrix[(a.name, b.name)] = bool(fn(a, b))
            except Exception as e:
                print(f"  ⚠️  {dsm.file_rel}: can_transition({a.name}, {b.name}) raised {type(e).__name__}: {e}")
                return None
    return member_names, matrix


TEST_TEMPLATE = '''\
"""
AUTO-GENERATED oleh tools/generate_state_transition_tests.py — JANGAN edit
manual kecuali Anda tahu konsekuensinya (lihat header file generator untuk
alasan kenapa test ini di-snapshot, bukan dihitung ulang secara dinamis).

Sumber   : {file_rel}
Enum     : {status_enum_name}
Pemilik can_transition: {transition_owner} ({call_style})

Regenerate setelah mengubah aturan transisi di source:
    python tools/generate_state_transition_tests.py --only {module_key} --force
"""

from __future__ import annotations

import pytest

from {module_path} import {status_enum_name}{extra_import}
from tests._helpers.state_machine_kit import (
    assert_no_self_transition,
    assert_transition_matrix,
)

_ALL_STATUSES = list({status_enum_name})

# Snapshot matriks transisi yang di-generate dari eksekusi kode ASLI pada saat
# generate dijalankan. True = transisi diperbolehkan, False = tidak.
_EXPECTED_MATRIX: dict[tuple[{status_enum_name}, {status_enum_name}], bool] = {{
{matrix_literal}
}}


def {call_fn_name}(frm: {status_enum_name}, to: {status_enum_name}) -> bool:
    """Wrapper tipis ke pemanggilan asli, supaya kit generik bisa dipakai."""
{call_body}


def test_{module_key}_full_transition_matrix():
    """Menutupi SELURUH {n_pairs} pasangan ({n_statuses} status x {n_statuses} status)
    dari state machine {status_enum_name}, termasuk semua jalur invalid
    (negative path)."""
    assert_transition_matrix(_EXPECTED_MATRIX, {call_fn_name})


@pytest.mark.parametrize("status", _ALL_STATUSES, ids=lambda s: s.name)
def test_{module_key}_no_self_transition(status):
    """Invariant umum: status tidak boleh 'bertransisi' ke dirinya sendiri.
    Kalau ada status yang MEMANG boleh (mis. DRAFT -> DRAFT untuk auto-save),
    tambahkan ke allowed_self_transitions di bawah dan jelaskan alasannya."""
    allowed_self_transitions: set[{status_enum_name}] = set()
    assert_no_self_transition([status], {call_fn_name}, allowed_self_transitions)
'''


def render_test_file(dsm: DiscoveredStateMachine, member_names: list[str], matrix: dict) -> str:
    module_key = dsm.file_rel.replace("/", "_").replace(".py", "").lower()
    lines = []
    for (a, b), result in matrix.items():
        lines.append(f"    ({dsm.status_enum_name}.{a}, {dsm.status_enum_name}.{b}): {result},")
    matrix_literal = "\n".join(lines)

    if dsm.call_style == "enum_classmethod":
        call_body = f"    return {dsm.status_enum_name}.can_transition(frm, to)"
        extra_import = ""
    elif dsm.call_style == "instance_method":
        call_body = "    return frm.can_transition_to(to)"
        extra_import = ""
    else:
        call_body = f"    return {dsm.transition_owner}.can_transition(frm, to)"
        extra_import = f", {dsm.transition_owner}"

    return TEST_TEMPLATE.format(
        file_rel=dsm.file_rel, status_enum_name=dsm.status_enum_name,
        transition_owner=dsm.transition_owner, call_style=dsm.call_style,
        module_key=module_key, module_path=dsm.module_path, extra_import=extra_import,
        matrix_literal=matrix_literal, call_fn_name=f"_call_{module_key}",
        call_body=call_body, n_pairs=len(matrix), n_statuses=len(member_names),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", default=None, help="Hanya proses file yang path-nya mengandung string ini")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="Timpa file test yang sudah ada")
    args = parser.parse_args()

    discovered = discover(args.only)
    print(f"Ditemukan {len(discovered)} state-machine pattern di domain layer.\n")

    generated = skipped = 0
    for dsm in discovered:
        print(f"→ {dsm.file_rel}  ({dsm.transition_owner}.{dsm.call_style})")
        result = build_matrix(dsm)
        if result is None:
            skipped += 1
            continue
        member_names, matrix = result

        domain_folder = dsm.file_rel.split("/")[1] if dsm.file_rel.startswith("domain/") else "misc"
        module_key = dsm.file_rel.replace("/", "_").replace(".py", "").lower()
        owner_slug = dsm.transition_owner.lower()
        out_dir = OUTPUT_ROOT / domain_folder
        out_file = out_dir / f"test_{module_key}_{owner_slug}_transition_matrix.py"

        if out_file.exists() and not args.force:
            print(f"  ⏭️  sudah ada, skip (pakai --force untuk timpa): {out_file.relative_to(ROOT)}")
            continue

        content = render_test_file(dsm, member_names, matrix)
        if args.dry_run:
            print(f"  [dry-run] akan menulis {out_file.relative_to(ROOT)} ({len(matrix)} pasangan)")
        else:
            out_dir.mkdir(parents=True, exist_ok=True)
            init_file = out_dir / "__init__.py"
            if not init_file.exists():
                init_file.write_text("", encoding="utf-8")
            out_file.write_text(content, encoding="utf-8")
            print(f"  ✅ ditulis: {out_file.relative_to(ROOT)} ({len(matrix)} pasangan, {len(member_names)} status)")
        generated += 1

    print(f"\nSelesai. {generated} file di-generate, {skipped} di-skip (lihat alasan di atas).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
