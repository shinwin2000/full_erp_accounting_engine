#!/usr/bin/env python3
"""
real_test_generator.py (Fixed Version)
Membaca semua file .py di direktori sumber dan menghasilkan file test pytest.
Versi ini aman dari error parameter 'self' pada class dan syntax error.
"""

import ast
import pathlib


class FunctionParser(ast.NodeVisitor):
    def __init__(self, source_file):
        self.source_file = source_file
        self.functions = []
        self.current_class = None

    def visit_ClassDef(self, node):
        old_class = self.current_class
        self.current_class = node.name
        self.generic_visit(node)
        self.current_class = old_class

    def visit_FunctionDef(self, node):
        self._process_function(node, is_async=False)

    def visit_AsyncFunctionDef(self, node):
        self._process_function(node, is_async=True)

    def _process_function(self, node, is_async):
        # Abaikan fungsi private (berawalan underscore)
        if node.name.startswith('_') and not node.name.startswith('__'):
            self.generic_visit(node)
            return

        # Ekstrak semua parameter
        args = [arg.arg for arg in node.args.args]

        # Ekstrak default values (hanya berlaku untuk N argumen terakhir)
        default_values = []
        for d in node.args.defaults:
            if isinstance(d, ast.Constant):
                default_values.append(repr(d.value))
            elif isinstance(d, ast.Name):
                default_values.append(d.id)
            elif isinstance(d, ast.Call) and isinstance(d.func, ast.Name):
                default_values.append(f"{d.func.id}()")
            else:
                default_values.append("None")

        # Pad defaults dengan None untuk argumen yang tidak punya default
        pad_len = len(args) - len(default_values)
        full_defaults = ["None"] * pad_len + default_values

        # Buang 'self' dan 'cls' dari parameter list agar tidak masuk ke parameter test
        final_params = []
        final_defaults = []
        for param, default in zip(args, full_defaults):
            if param not in ('self', 'cls'):
                final_params.append(param)
                final_defaults.append(default)

        self.functions.append({
            'name': node.name,
            'class': self.current_class,
            'params': final_params,
            'defaults': final_defaults,
            'is_async': is_async,
            'lineno': node.lineno,
        })
        self.generic_visit(node)

def generate_test_for_function(func_info):
    name = func_info['name']
    params = func_info['params']
    defaults = func_info['defaults']
    is_async = func_info['is_async']
    class_name = func_info['class']

    # Buat string argumen (misal: "total=None, diskon=10")
    arg_str = ', '.join([f"{p}={d}" for p, d in zip(params, defaults)]) if params else ''

    lines = []
    test_name = f"test_{class_name}_{name}" if class_name else f"test_{name}"

    if is_async:
        lines.append("@pytest.mark.asyncio")
        lines.append(f"async def {test_name}():")
    else:
        lines.append(f"def {test_name}():")

    lines.append("    # TODO: sesuaikan parameter dummy dan assertion")

    # Jika fungsi berada di dalam class, kita harus inisialisasi class-nya dulu
    if class_name:
        lines.append("    # Inisialisasi object class")
        lines.append(f"    instance = {class_name}()")
        caller = f"instance.{name}"
    else:
        caller = f"{name}"

    if is_async:
        lines.append(f"    result = await {caller}({arg_str})")
    else:
        lines.append(f"    result = {caller}({arg_str})")

    lines.append(f'    assert result is not None, "{name} mengembalikan None"')
    lines.append("")

    return '\n'.join(lines)

def process_source_file(source_path):
    with open(source_path, encoding='utf-8') as f:
        source = f.read()

    tree = ast.parse(source)
    parser = FunctionParser(source_path)
    parser.visit(tree)

    # Generate import path
    rel_path = source_path.relative_to(pathlib.Path.cwd())
    module_name = str(rel_path).replace('/', '.').replace('\\', '.').replace('.py', '')

    test_lines = [
        "import pytest",
        "from decimal import Decimal",
        f"from {module_name} import *",
        ""
    ]

    for func in parser.functions:
        test_lines.append(generate_test_for_function(func))

    return '\n'.join(test_lines), len(parser.functions)

def main():
    # Elipsis (...) dihapus. Tentukan folder yang ingin dipindai:
    source_dirs = ['domain', 'application', 'adapters', 'infrastructure']

    total_files = 0
    total_tests = 0

    print("🚀 Memulai proses generate Real Test...")

    for src_dir in source_dirs:
        src_path = pathlib.Path(src_dir)

        # Validasi jika folder tidak ada
        if not src_path.exists():
            print(f"⚠️ Folder '{src_dir}' tidak ditemukan, melewati...")
            continue

        for py_file in src_path.rglob('*.py'):
            if '__init__' in py_file.name or py_file.name.startswith('test_'):
                continue

            # Tambahkan awalan 'test_' ke nama file agar terdeteksi pytest
            test_filename = f"test_{py_file.name}"
            output_path = pathlib.Path('tests/auto_generated') / py_file.parent / test_filename
            output_path.parent.mkdir(parents=True, exist_ok=True)

            test_code, func_count = process_source_file(py_file)

            # Hanya buat file jika ada fungsi yang ditemukan
            if func_count > 0:
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(test_code)
                print(f"✅ Generated: {output_path} ({func_count} tests)")
                total_files += 1
                total_tests += func_count

    print(f"\n🎯 Selesai! Berhasil membuat {total_tests} kerangka test di {total_files} file.")

if __name__ == '__main__':
    main()
