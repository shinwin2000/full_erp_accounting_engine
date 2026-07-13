#!/usr/bin/env python3
"""
AUTO TEST GENERATOR v1.0
Memindai folder sumber dan menghasilkan file test pytest secara otomatis.
Fokus pada fungsi dengan business logic tinggi (accounting, inventory, dll).

Cara pakai:
    python auto_test_generator.py --target-dir app/accounting --limit 50
    python auto_test_generator.py --target-dir domain/inventory --limit 20
"""

import argparse
import ast
import os
import pathlib

# ===================================================================
# 1. PARSER UNTUK DETEKSI FUNGSI & EXCEPTION
# ===================================================================

class FunctionExtractor(ast.NodeVisitor):
    def __init__(self):
        self.functions = []  # list of dict
        self.current_class = None

    def visit_ClassDef(self, node):
        old_class = self.current_class
        self.current_class = node.name
        self.generic_visit(node)
        self.current_class = old_class

    def visit_FunctionDef(self, node):
        self._process_function(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node):
        self._process_function(node)
        self.generic_visit(node)

    def _process_function(self, node):
        if node.name.startswith('_') and not node.name.startswith('__'):
            return
        # Ambil parameter
        params = [arg.arg for arg in node.args.args]
        # Cari exception yang di-raise
        raises = set()
        for child in ast.walk(node):
            if isinstance(child, ast.Raise):
                if isinstance(child.exc, ast.Call):
                    if isinstance(child.exc.func, ast.Name):
                        raises.add(child.exc.func.id)
                    elif isinstance(child.exc.func, ast.Attribute):
                        raises.add(child.exc.func.attr)
                elif isinstance(child.exc, ast.Name):
                    raises.add(child.exc.id)
        # Cek decorators (async, db, dll)
        decorators = []
        for dec in node.decorator_list:
            if isinstance(dec, ast.Name):
                decorators.append(dec.id)
            elif isinstance(dec, ast.Attribute):
                decorators.append(dec.attr)
        is_async = isinstance(node, ast.AsyncFunctionDef)
        self.functions.append({
            'name': node.name,
            'class_name': self.current_class,
            'params': params,
            'raises': list(raises),
            'decorators': decorators,
            'is_async': is_async,
            'lineno': node.lineno,
        })


def scan_source_file(filepath: pathlib.Path) -> list[dict]:
    """Scan satu file Python, ekstrak semua fungsi."""
    try:
        source = filepath.read_text(encoding='utf-8')
        tree = ast.parse(source)
        extractor = FunctionExtractor()
        extractor.visit(tree)
        return extractor.functions
    except Exception as e:
        print(f"  ⚠️  Gagal parsing {filepath}: {e}")
        return []


def scan_directory(target_dir: pathlib.Path, limit: int = None) -> dict[str, list[dict]]:
    """Scan semua file .py di target_dir."""
    print(f"🔍 Memindai: {target_dir}")
    results = {}
    py_files = list(target_dir.rglob('*.py'))
    py_files = [f for f in py_files if not f.name.startswith('test_') and '__init__' not in f.name]
    if limit:
        py_files = py_files[:limit * 2]  # oversample karena mungkin banyak yang kosong
    total_files = len(py_files)
    for i, py_file in enumerate(py_files):
        funcs = scan_source_file(py_file)
        if funcs:
            # Filter fungsi yang memiliki business logic (accounting/inventory)
            # Kita tetap ambil semua, nanti disaring di output
            results[str(py_file)] = funcs
        if (i + 1) % 20 == 0:
            print(f"  Progress: {i+1}/{total_files}")
    return results


# ===================================================================
# 2. GENERATOR TEST SKELETON
# ===================================================================

def generate_test_for_function(func: dict, source_file: str) -> str:
    """Buat kode test untuk satu fungsi."""
    name = func['name']
    class_name = func.get('class_name')
    params = func['params']
    raises = func['raises']
    is_async = func['is_async']

    # Tentukan fixture mapping
    fixture_map = {
        'session': 'db_session',
        'db': 'db_session',
        'uow': 'unit_of_work',
        'conn': 'db_connection',
        'client': 'test_client',
    }
    param_fixtures = []
    for p in params:
        if p in fixture_map:
            param_fixtures.append(fixture_map[p])
        elif p in ('mock', 'mocker', 'mock_fixture'):
            param_fixtures.append('mocker')
        else:
            # Coba tebak dari nama
            if 'repo' in p.lower() or 'service' in p.lower():
                param_fixtures.append(p)
            else:
                param_fixtures.append(p)

    # Import statements
    imports = [
        "import pytest",
        "from decimal import Decimal",
        f"from {source_file.replace(os.sep, '.').replace('.py', '')} import {name if not class_name else class_name}",
    ]
    if class_name:
        imports.append(f"from {source_file.replace(os.sep, '.').replace('.py', '')} import {class_name}")

    # Body test
    body = []
    # Async handling
    if is_async:
        body.append("    @pytest.mark.asyncio")
    body.append(f"    async def test_{name}_success({', '.join(param_fixtures)}):")
    body.append('        """TODO: Test skenario sukses untuk {}""".format("{}:{}".format("' + source_file + '", "' + name + '")))')
    body.append("        # Arrange")
    # Generate arrange suggestions
    if 'Decimal' in str(params):
        body.append("        # TODO: Buat data dengan Decimal('...')")
    body.append("        # Act")
    if is_async:
        body.append(f"        result = await {name}({', '.join(params)})")
    else:
        body.append(f"        result = {name}({', '.join(params)})")
    body.append("        # Assert")
    body.append("        # TODO: Tambahkan assertion yang spesifik")
    body.append("        assert result is not None  # placeholder")
    body.append("")

    # Test untuk exception
    if raises:
        for exc in raises[:3]:  # maks 3 exception per fungsi
            body.append(f"    def test_{name}_raises_{exc}({', '.join(param_fixtures)}):")
            body.append(f'        """TODO: Test bahwa {name} melempar {exc} pada kondisi error."""')
            # Buat parameter invalid untuk memicu error (hanya placeholder)
            body.append("        # Arrange - buat parameter invalid")
            body.append("        # Act & Assert")
            if is_async:
                body.append(f"        with pytest.raises({exc}):")
                body.append(f"            await {name}({', '.join(['invalid' for _ in params])})")
            else:
                body.append(f"        with pytest.raises({exc}):")
                body.append(f"            {name}({', '.join(['invalid' for _ in params])})")
            body.append("")

    if not body:
        return ""

    # Gabungkan
    header = "# AUTO-GENERATED TEST SKELETON\n"
    header += "# =================================\n"
    header += f"# Source: {source_file}\n"
    header += f"# Function: {name}\n"
    header += "# TODO: Sesuaikan fixture, data, dan assertion\n\n"
    header += "\n".join(imports)
    header += "\n\n"
    if class_name:
        header += f"# Test untuk class {class_name}\n"
    header += "\n".join(body)

    return header


def generate_test_file(source_file: str, functions: list[dict], output_root: pathlib.Path) -> pathlib.Path:
    """Generate file test untuk satu source file."""
    if not functions:
        return None

    # Buat path output: tests/auto_generated/<source_dir>/test_<source_file>
    rel_path = pathlib.Path(source_file)
    # Tentukan nama output
    test_filename = f"test_{rel_path.name}"
    output_dir = output_root / "auto_generated" / rel_path.parent
    output_path = output_dir / test_filename

    output_dir.mkdir(parents=True, exist_ok=True)

    # Generate content
    content = f"# AUTO-GENERATED TESTS for {rel_path}\n"
    content += "# =========================================\n"
    content += "# DIBUAT OTOMATIS oleh auto_test_generator.py\n"
    content += f"# Jumlah fungsi: {len(functions)}\n"
    content += "# TODO: Lengkapi assertion dan fixture\n\n"
    content += "import pytest\n"
    content += "from decimal import Decimal\n"

    # Impor source file (relative)
    # Karena file test berada di tests/auto_generated, import relatif ke root
    # Misal source di app/accounting/journal.py -> from app.accounting.journal import ...
    import_path = rel_path.with_suffix('').as_posix().replace('/', '.')
    content += f"from {import_path} import *\n\n"

    for func in functions:
        content += "# " + "=" * 60 + "\n"
        content += f"# Function: {func['name']}\n"
        if func['class_name']:
            content += f"# Class: {func['class_name']}\n"
        content += f"# Params: {func['params']}\n"
        content += f"# Raises: {func['raises']}\n"
        content += "# " + "=" * 60 + "\n"
        # Buat fixture placeholder jika perlu
        if func['params'] and not any(p in func['params'] for p in ['self', 'cls']):
            # Tentukan fixture
            for p in func['params']:
                if p not in ['self', 'cls']:
                    content += "@pytest.fixture\n"
                    content += f"def {p}_fixture():\n"
                    content += f"    # TODO: Buat fixture untuk parameter '{p}'\n"
                    content += "    return None\n\n"
        # Test success
        content += generate_test_for_function(func, import_path)
        content += "\n\n"

    # Write file
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(content)
    return output_path


# ===================================================================
# 3. MAIN
# ===================================================================

def main():
    parser = argparse.ArgumentParser(description="Auto generate pytest skeletons")
    parser.add_argument('--target-dir', required=True, help='Direktori source (contoh: app/accounting)')
    parser.add_argument('--limit', type=int, help='Batas maksimum file yang diproses')
    parser.add_argument('--output', default='tests', help='Root folder output (default: tests)')
    args = parser.parse_args()

    target = pathlib.Path(args.target_dir)
    if not target.exists():
        print(f"❌ Target dir tidak ditemukan: {target}")
        return 1

    output_root = pathlib.Path(args.output)
    print(f"📂 Output akan disimpan di: {output_root}/auto_generated/")

    # Scan
    results = scan_directory(target, args.limit)

    total_files = 0
    total_funcs = 0
    generated = 0

    for source_file, funcs in results.items():
        if not funcs:
            continue
        # Filter fungsi yang tidak private (sudah di filter di parser)
        total_files += 1
        total_funcs += len(funcs)
        out_path = generate_test_file(source_file, funcs, output_root)
        if out_path:
            generated += 1
            print(f"✅ Generated: {out_path} ({len(funcs)} functions)")

    print("\n🎯 Selesai!")
    print(f"   Total file diproses: {total_files}")
    print(f"   Total fungsi ditemukan: {total_funcs}")
    print(f"   File test dibuat: {generated}")
    print("\n🔧 Langkah selanjutnya:")
    print(f"   1. Buka folder {output_root}/auto_generated/")
    print("   2. Lengkapi bagian # TODO dengan logic bisnis yang tepat.")
    print(f"   3. Jalankan pytest untuk verifikasi: pytest {output_root}/auto_generated/ -v")

    return 0


if __name__ == "__main__":
    exit(main())
