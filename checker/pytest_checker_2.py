"""
PYTEST QUALITY CHECKER v6.2.0 - DETAILED WEAK REPORT
----------------------------------------------------
Fitur:
1. Auto-exclude folder venv, .git, __pycache__, etc.
2. Handling encoding error dengan utf-8 errors='ignore'.
3. Logika weak assertion yang lebih pintar:
   - assert True/False/None/0/"" dianggap LEMAH.
   - assert x == True / assert True == x dianggap LEMAH.
   - assert x is not None, assert x > 0, assert len(x) > 0 dianggap KUAT.
4. Laporan menampilkan 8 file dengan weak assertion terbanyak, lengkap dengan baris-baris lemahnya.
5. Output JSON dengan ringkasan dan detail weak per file.

Changelog v6.2.0 (bugfix):
- FIX: deteksi "comparison with boolean literal" sebelumnya hanya mengecek
  sisi kanan (test_node.comparators), sehingga pola literal-di-kiri seperti
  `assert True == x` lolos tanpa terdeteksi. Sekarang test_node.left juga
  diperiksa.
"""

import ast
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

# --- KONFIGURASI ---
EXCLUDE_DIRS = {'venv', '.git', '__pycache__', 'node_modules', '.idea', '.vscode', 'build', 'dist'}

class AssertAnalyzer(ast.NodeVisitor):
    def __init__(self):
        self.asserts = []          # list of dict per assert
        self.test_functions = 0
        self.current_test_name = None

    def visit_FunctionDef(self, node):
        if node.name.startswith('test_'):
            self.test_functions += 1
            self.current_test_name = node.name
            self.generic_visit(node)
            self.current_test_name = None
        else:
            self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node):
        if node.name.startswith('test_'):
            self.test_functions += 1
            self.current_test_name = node.name
            self.generic_visit(node)
            self.current_test_name = None
        else:
            self.generic_visit(node)

    def visit_Assert(self, node):
        analysis = self._analyze_assert_node(node)
        if analysis:
            analysis['line'] = node.lineno
            analysis['test_function'] = self.current_test_name or "<module_level>"
            self.asserts.append(analysis)
        self.generic_visit(node)

    def _analyze_assert_node(self, node) -> dict[str, Any] | None:
        test_node = node.test
        msg_node = node.msg

        result = {
            'code': ast.unparse(test_node),
            'has_msg': msg_node is not None,
            'msg': ast.unparse(msg_node) if msg_node else None,
            'is_weak': False,
            'weak_reason': None,
            'category': 'unknown'
        }

        # 1. Konstanta langsung
        if isinstance(test_node, ast.Constant):
            val = test_node.value
            if isinstance(val, bool):
                result['is_weak'] = True
                result['weak_reason'] = f"Boolean constant ({val})"
                result['category'] = 'constant_bool'
            elif val is None:
                result['is_weak'] = True
                result['weak_reason'] = "None constant"
                result['category'] = 'constant_none'
            elif isinstance(val, (int, float)) and val == 0:
                result['is_weak'] = True
                result['weak_reason'] = "Zero constant"
                result['category'] = 'constant_num'
            elif isinstance(val, str) and val == "":
                result['is_weak'] = True
                result['weak_reason'] = "Empty string constant"
                result['category'] = 'constant_str'
            return result

        # 2. Comparison
        if isinstance(test_node, ast.Compare):
            ops = test_node.ops
            comparators = test_node.comparators
            op_names = [type(op).__name__ for op in ops]

            # Deteksi pola lemah: x == True, x != False, True == x, False != x
            # Operand kiri (test_node.left) dicek berdasarkan operator pertama;
            # operand kanan (comparators[i]) dicek berdasarkan op_names[i].
            weak_operands = [(test_node.left, op_names[0])] if op_names else []
            weak_operands += list(zip(comparators, op_names))
            for comp, op_name in weak_operands:
                if isinstance(comp, ast.Constant) and isinstance(comp.value, bool):
                    if op_name in ['Eq', 'NotEq']:
                        result['is_weak'] = True
                        result['weak_reason'] = f"Comparison with boolean literal ({comp.value}) using {op_name}"
                        result['category'] = 'comparison_literal_bool'
                        return result

            # Semua comparison lain dianggap KUAT (termasuk is None, >0, == bilangan tertentu, dll)
            result['category'] = 'comparison_valid'
            if 'Is' in op_names or 'IsNot' in op_names:
                result['category'] = 'null_check'
            return result

        # 3. Call (pytest.raises, dll) => KUAT
        if isinstance(test_node, ast.Call):
            func = test_node.func
            func_name = ""
            if isinstance(func, ast.Name):
                func_name = func.id
            elif isinstance(func, ast.Attribute):
                func_name = func.attr
            if 'raise' in func_name.lower():
                result['category'] = 'exception_check'
            else:
                result['category'] = 'function_call'
            return result

        # Ekspresi lain dianggap KUAT
        result['category'] = 'expression'
        return result


class PytestChecker:
    def __init__(self, root_dir: str):
        self.root_dir = Path(root_dir)
        self.stats = {
            'total_files': 0,
            'scanned_files': 0,
            'files_with_tests': 0,
            'total_asserts': 0,
            'strong_asserts': 0,
            'weak_asserts': 0,
            'total_lines': 0
        }
        # Simpan semua weak assertion per file
        self.weak_by_file = defaultdict(list)   # file_path -> list of weak assert dict
        self.encoding_errors = []

    def should_exclude(self, path: Path) -> bool:
        parts = path.parts
        for part in parts:
            if part in EXCLUDE_DIRS:
                return True
        return False

    def scan_directory(self):
        print(f"🔍 Scanning directory: {self.root_dir.absolute()} ...")
        print(f"   Excluding folders: {', '.join(EXCLUDE_DIRS)}")

        py_files = []
        for root, dirs, files in os.walk(self.root_dir):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
            for file in files:
                if file.endswith('.py'):
                    py_files.append(Path(root) / file)

        self.stats['total_files'] = len(py_files)

        for filepath in py_files:
            self._process_file(filepath)

    def _process_file(self, filepath: Path):
        try:
            content = filepath.read_text(encoding='utf-8', errors='ignore')
            lines = content.splitlines()
            self.stats['total_lines'] += len(lines)

            tree = ast.parse(content, filename=str(filepath))
            analyzer = AssertAnalyzer()
            analyzer.visit(tree)

            if analyzer.asserts or analyzer.test_functions > 0:
                self.stats['scanned_files'] += 1
                if analyzer.test_functions > 0:
                    self.stats['files_with_tests'] += 1

                for ass in analyzer.asserts:
                    self.stats['total_asserts'] += 1
                    if ass['is_weak']:
                        self.stats['weak_asserts'] += 1
                        # Simpan weak assertion dengan informasi file
                        rel_path = str(filepath.relative_to(self.root_dir))
                        self.weak_by_file[rel_path].append({
                            'line': ass['line'],
                            'code': ass['code'],
                            'reason': ass['weak_reason'],
                            'test_function': ass['test_function']
                        })
                    else:
                        self.stats['strong_asserts'] += 1

        except SyntaxError:
            # Skip file dengan syntax error
            pass
        except Exception as e:
            self.encoding_errors.append(f"{filepath}: {e!s}")

    def generate_report(self):
        total = self.stats['total_asserts']
        strong = self.stats['strong_asserts']
        quality_score = (strong / total * 100) if total > 0 else 0.0
        threshold = 70.0
        status = "✅ PASS" if quality_score >= threshold else "❌ FAIL"

        # Print Header
        print("\n" + "="*60)
        print("🔍 PYTEST ASSERTION QUALITY REPORT")
        print("="*60)
        print(f"📂 Files Scanned       : {self.stats['scanned_files']} (Total found: {self.stats['total_files']})")
        print(f"🧪 Files with Tests    : {self.stats['files_with_tests']}")
        print(f"📊 Total Assertions    : {total}")
        print("-" * 60)
        print(f"✅ Strong Assertions   : {strong}")
        print(f"❌ Weak Assertions     : {self.stats['weak_asserts']}")
        print("-" * 60)
        print(f"🏆 Quality Score       : {quality_score:.2f}%")
        print(f"🎯 Threshold           : {threshold}%")
        print(f"🚦 Status              : {status}")
        print("="*60)

        # Encoding errors
        if self.encoding_errors:
            print(f"\n⚠️  Encoding/Syntax warnings on {len(self.encoding_errors)} files (Ignored safely):")
            for err in self.encoding_errors[:5]:
                print(f"   • {err}")
            if len(self.encoding_errors) > 5:
                print(f"   ... and {len(self.encoding_errors) - 5} more.")

        # --- TAMPILKAN 8 FILE DENGAN WEAK TERBANYAK ---
        if self.weak_by_file:
            # Urutkan file berdasarkan jumlah weak descending
            sorted_files = sorted(self.weak_by_file.items(), key=lambda x: len(x[1]), reverse=True)
            top8 = sorted_files[:8]

            print("\n" + "="*60)
            print("⚠️  TOP 8 FILES WITH MOST WEAK ASSERTIONS")
            print("="*60)

            for file_path, weak_list in top8:
                print(f"\n📄 {file_path}  ({len(weak_list)} weak assertions)")
                # Tampilkan maksimal 10 baris per file agar tidak overflow
                for idx, w in enumerate(weak_list[:10], 1):
                    print(f"   Line {w['line']:4d} : {w['reason']}")
                    print(f"         Code: assert {w['code']}")
                if len(weak_list) > 10:
                    print(f"   ... and {len(weak_list) - 10} more weak assertions in this file.")
                print("-" * 40)

        else:
            print("\n✅ Tidak ditemukan weak assertion!")

        # Tips
        print("\n💡 Tip: Perbaiki assertion lemah agar skor mencapai 100%.")
        print("   Hindari: assert True, assert x == True")
        print("   Gunakan: assert x is True, assert condition, assert len(x) > 0")
        print("   Catatan: 'assert x is not None' dan 'assert x > 0' sudah dianggap KUAT.")

        # Save JSON
        report_data = {
            'summary': self.stats,
            'quality_score': quality_score,
            'threshold': threshold,
            'status': status,
            'weak_by_file': {
                file: [
                    {'line': w['line'], 'code': w['code'], 'reason': w['reason']}
                    for w in weak_list
                ]
                for file, weak_list in self.weak_by_file.items()
            }
        }
        output_file = "pytest_quality_report.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(report_data, f, indent=2, ensure_ascii=False)

        print(f"\n📄 Detailed report saved to: {output_file}")
        print("="*60)


def main():
    target_dir = sys.argv[1] if len(sys.argv) > 1 else "."
    if not os.path.isdir(target_dir):
        print(f"Error: '{target_dir}' is not a valid directory.")
        sys.exit(1)

    checker = PytestChecker(target_dir)
    checker.scan_directory()
    checker.generate_report()


if __name__ == "__main__":
    main()
