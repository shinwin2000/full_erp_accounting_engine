#!/usr/bin/env python3
"""
pytest_checker.py - Advanced Pytest Quality Analyzer

Alat analisis statis mendalam untuk mengukur kualitas, cakupan, dan ketepatan
suite pengujian pytest. Menggunakan AST (Abstract Syntax Tree) untuk menghindari
false positive dan memberikan metrik berbasis kode nyata (real code).

Fitur Utama:
- Deteksi Assertion Bermakna (mengabaikan assert True/False/None)
- Analisis Negative Path (pytest.raises, try/except)
- Dukungan Parametrized Tests (menghitung kombinasi kasus)
- Skor Kualitas Berbasis Kompleksitas
- Ekspor Laporan JSON Lengkap
- Deteksi Edge Cases dan Boundary Conditions
- Tampilan top N file dengan assertion lemah (bisa diatur)

Versi: 5.3.0

Changelog v5.3.0 (bugfix):
- FIX BUG KRITIS: sebelumnya setiap assertion Compare yang salah satu
  operand-nya berupa literal dalam _WEAK_CONSTANT_VALUES (True/False/None/0/1/"")
  langsung dicap "weak" TANPA memeriksa operatornya. Akibatnya
  `assert x is not None` dan `assert x > 0` — dua pola assertion yang
  seharusnya KUAT — ikut ditandai lemah, bertentangan dengan dokumentasi
  fungsi ini sendiri. Sekarang logikanya membedakan:
    * Eq/NotEq terhadap literal boolean (True/False)  -> LEMAH (redundan)
    * Eq/NotEq terhadap None (assert x == None)        -> LEMAH (harus pakai 'is')
    * SEMUA operator lain (Is/IsNot/Gt/Lt/Ge/Le/In/NotIn),
      termasuk terhadap None/0/1/""                    -> TETAP KUAT
"""

import argparse
import ast
import json
import logging
import re
import sys
import traceback
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

# Konfigurasi Logging
logging.basicConfig(level=logging.CRITICAL, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# ==============================================================================
# KONSTANTA & AMBANG BATAS (THRESHOLDS)
# ==============================================================================

# Ambang batas kualitas minimal yang dapat diterima
THRESHOLD_ASSERTION_QUALITY = 70.0  # % assertion yang bermakna
THRESHOLD_NEGATIVE_PATH_COVERAGE = 15.0  # % tes yang menguji error/failure
MIN_ASSERTIONS_PER_TEST = 1.0

# Pola nama fungsi tes
TEST_FUNCTION_PATTERN = re.compile(r'^test_|^should_|^it_')

# Daftar nilai konstanta yang dianggap "lemah" atau "tidak bermakna" ketika
# muncul sebagai TEST NODE LANGSUNG (mis. `assert True`, `assert 0`, `assert ""`).
# (hanya nilai hashable; untuk list/dict kosong gunakan fungsi is_weak_constant)
_WEAK_CONSTANT_VALUES = {True, False, None, ""}

def is_weak_constant(value: Any) -> bool:
    """Memeriksa apakah nilai konstanta dianggap lemah saat menjadi TEST NODE
    langsung sebuah assert (bukan operand di dalam comparison). Contoh:
    `assert True`, `assert None`, `assert 0`, `assert ""` -> lemah, karena
    tidak menguji apa pun secara spesifik."""
    if value in _WEAK_CONSTANT_VALUES:
        return True
    # Periksa container kosong (list, tuple, dict, set, frozenset)
    if isinstance(value, (list, tuple, dict, set, frozenset)) and len(value) == 0:
        return True
    return False


def is_redundant_comparison_operand(value: Any, op: type) -> bool:
    """Memeriksa apakah literal `value` di salah satu sisi sebuah `Compare`
    node membuat perbandingan tsb REDUNDAN, dengan MEMPERHATIKAN operatornya.

    PENTING: ini BEDA dari is_weak_constant(). Membandingkan sesuatu dengan
    0/None/1/"" pakai operator seperti >, <, is, is not, >=, <= adalah pola
    assertion yang KUAT dan spesifik (mis. `assert x > 0`, `assert x is not
    None`) -- BUKAN redundan -- sehingga tidak boleh ditandai lemah. Hanya
    Eq/NotEq terhadap boolean literal (dan Eq/NotEq terhadap None, yang
    seharusnya ditulis pakai `is`/`is not`) yang dianggap redundan.
    """
    if op not in (ast.Eq, ast.NotEq):
        return False
    if isinstance(value, bool):
        return True
    if value is None:
        return True
    return False

# ==============================================================================
# STRUKTUR DATA (DATA CLASSES)
# ==============================================================================

@dataclass
class AssertionDetail:
    """Menyimpan detail spesifik tentang sebuah assertion."""
    line_number: int
    code_snippet: str
    assertion_type: str  # 'compare', 'call', 'attribute', 'constant'
    is_meaningful: bool
    reason: str
    has_message: bool
    involves_boolean_constant: bool = False
    complexity_score: float = 1.0

@dataclass
class TestFunctionDetail:
    """Menyimpan detail tentang sebuah fungsi tes."""
    name: str
    line_start: int
    line_end: int
    parametrize_count: int = 1  # Jumlah kombinasi jika parametrized
    assertions: list[AssertionDetail] = field(default_factory=list)
    has_negative_path: bool = False
    negative_path_type: str = ""  # 'raises', 'try_except', 'assert_raises'
    complexity_score: float = 0.0

@dataclass
class FileAnalysisResult:
    """Hasil analisis per file."""
    filepath: str
    total_lines: int
    test_functions: list[TestFunctionDetail] = field(default_factory=list)
    total_assertions: int = 0
    meaningful_assertions: int = 0
    weak_assertions: int = 0
    error_during_analysis: str | None = None

@dataclass
class GlobalMetrics:
    """Metrik global agregat."""
    total_files_scanned: int = 0
    total_test_files: int = 0
    total_test_functions: int = 0
    total_weighted_tests: int = 0  # Memperhitungkan parametrized tests
    total_assertions: int = 0
    total_meaningful_assertions: int = 0
    total_weak_assertions: int = 0
    files_with_negative_path: int = 0
    total_negative_path_tests: int = 0
    average_assertions_per_test: float = 0.0
    assertion_quality_score: float = 0.0
    negative_path_coverage: float = 0.0
    detailed_file_results: dict[str, Any] = field(default_factory=dict)

# ==============================================================================
# ANALISER AST (ABSTRACT SYNTAX TREE)
# ==============================================================================

class DeepTestAnalyzer(ast.NodeVisitor):
    """
    Visitor AST untuk menganalisis struktur tes secara mendalam.
    Mendeteksi assertion, negative path, dan kompleksitas.
    """

    def __init__(self, source_code: str):
        self.source_code = source_code
        self.source_lines = source_code.splitlines()
        self.test_functions: list[TestFunctionDetail] = []
        self.current_function: TestFunctionDetail | None = None
        self.in_try_block = False

    def visit_Module(self, node):
        for child in node.body:
            self.visit(child)

    def visit_FunctionDef(self, node):
        if TEST_FUNCTION_PATTERN.match(node.name):
            # Hitung jumlah parameter jika ada @pytest.mark.parametrize
            param_count = self._count_parametrize_variants(node)

            func_detail = TestFunctionDetail(
                name=node.name,
                line_start=node.lineno,
                line_end=node.end_lineno or node.lineno,
                parametrize_count=param_count
            )
            self.current_function = func_detail

            # Kunjungi body fungsi untuk mencari assertion dan pola lain
            for child in node.body:
                self.visit(child)

            # Hitung skor kompleksitas sederhana berdasarkan panjang dan cabang
            func_detail.complexity_score = self._calculate_complexity(node)
            self.test_functions.append(func_detail)
            self.current_function = None
        else:
            # Tetap kunjungi fungsi helper di dalam file tes
            self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node):
        # Perlakukan async test functions sama seperti biasa
        self.visit_FunctionDef(node)

    def visit_Assert(self, node):
        if self.current_function is None:
            return

        snippet = self._get_line_snippet(node.lineno)
        analysis = self._analyze_assert_node(node, snippet)

        self.current_function.assertions.append(analysis)

        # Jangan kunjungi children dari assert karena sudah dianalisis
        # self.generic_visit(node)

    def visit_With(self, node):
        """Mendeteksi context manager seperti pytest.raises."""
        if self.current_function is None:
            return

        for item in node.items:
            if isinstance(item.context_expr, ast.Call):
                func = item.context_expr.func
                func_name = ""
                if isinstance(func, ast.Name):
                    func_name = func.id
                elif isinstance(func, ast.Attribute):
                    func_name = func.attr

                if 'raise' in func_name.lower():
                    self.current_function.has_negative_path = True
                    self.current_function.negative_path_type = f"context_manager:{func_name}"

        self.generic_visit(node)

    def visit_Try(self, node):
        """Mendeteksi blok try/except sebagai bentuk negative path testing."""
        if self.current_function is None:
            return

        if node.handlers:
            self.current_function.has_negative_path = True
            self.current_function.negative_path_type = "try_except_block"

        self.generic_visit(node)

    def _count_parametrize_variants(self, node: ast.FunctionDef) -> int:
        """Menghitung berapa banyak kasus uji yang dihasilkan oleh parametrized."""
        count = 1
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Call):
                func_name = ""
                if isinstance(decorator.func, ast.Name):
                    func_name = decorator.func.id
                elif isinstance(decorator.func, ast.Attribute):
                    func_name = decorator.func.attr

                if 'parametrize' in func_name.lower():
                    args = decorator.args
                    if len(args) >= 2:
                        second_arg = args[1]
                        if isinstance(second_arg, ast.List):
                            count = len(second_arg.elts)
                        elif isinstance(second_arg, ast.Tuple):
                            # Bisa berupa list of tuples atau range
                            # Estimasi konservatif jika kompleks
                            count = max(1, len(second_arg.elts))
        return count

    def _analyze_assert_node(self, node: ast.Assert, snippet: str) -> AssertionDetail:
        """Menganalisis node assert untuk menentukan kualitasnya."""
        test_node = node.test
        is_meaningful = True
        reason = "Standard assertion"
        involves_bool_const = False
        complexity = 1.0

        # 1. Cek Constant Langsung (assert True, assert False)
        if isinstance(test_node, ast.Constant):
            val = test_node.value
            if is_weak_constant(val):
                is_meaningful = False
                reason = f"Assertion terhadap konstanta tetap ({val}) tidak menguji logika apapun."
                involves_bool_const = (val in (True, False, None))
            else:
                reason = "Assertion terhadap nilai konstan non-boolean"

        # 2. Cek Comparison (x == y, x is True, dll)
        elif isinstance(test_node, ast.Compare):
            ops = test_node.ops
            comparators = test_node.comparators

            # Pasangkan tiap operator dengan operand di sisi kanannya, plus
            # operand kiri (test_node.left) dengan operator pertama, supaya
            # pola literal-di-kiri (mis. `assert True == x`) juga tertangkap.
            paired_operands = []
            if ops:
                paired_operands.append((test_node.left, ops[0]))
            paired_operands += list(zip(comparators, ops))

            # FIX v5.3.0: redundansi HARUS mempertimbangkan operatornya.
            # `assert x is not None` dan `assert x > 0` BUKAN redundan meski
            # operand-nya None/0 -- hanya Eq/NotEq terhadap boolean atau None
            # yang redundan.
            for comp, op in paired_operands:
                if isinstance(comp, ast.Constant) and is_redundant_comparison_operand(comp.value, type(op)):
                    involves_bool_const = isinstance(comp.value, bool)
                    is_meaningful = False
                    if isinstance(comp.value, bool):
                        reason = "Perbandingan eksplisit dengan boolean constant (redundan)."
                    else:
                        reason = "Perbandingan eksplisit dengan None memakai ==/!= (gunakan 'is'/'is not')."
                    break

            if is_meaningful:
                # Cek operator
                for op in ops:
                    if isinstance(op, (ast.In, ast.NotIn)):
                        complexity = 1.5 # Sedikit lebih kompleks
                    elif isinstance(op, (ast.Is, ast.IsNot)):
                         complexity = 1.2
                reason = f"Comparison menggunakan operator {[type(o).__name__ for o in ops]}"

        # 3. Cek Call (assert func(), assert raises())
        elif isinstance(test_node, ast.Call):
            func = test_node.func
            fname = ""
            if isinstance(func, ast.Name): fname = func.id
            elif isinstance(func, ast.Attribute): fname = func.attr

            if 'raise' in fname.lower():
                # Ini sebenarnya jarang terjadi langsung di dalam assert,
                # biasanya pakai with pytest.raises. Tapi kalau ada:
                reason = "Assertion memanggil fungsi raise-related"
                complexity = 2.0
            else:
                reason = "Assertion hasil pemanggilan fungsi"
                complexity = 1.5

        # 4. Cek Boolean Ops (and, or)
        elif isinstance(test_node, ast.BoolOp):
            complexity = 1.0 + (len(test_node.values) * 0.5)
            reason = "Assertion dengan operasi boolean majemuk"

            # Cek apakah semua value di dalamnya constant yang lemah
            all_weak = all(
                isinstance(v, ast.Constant) and is_weak_constant(v.value)
                for v in test_node.values
            )
            if all_weak:
                is_meaningful = False
                reason = "Operasi boolean sepenuhnya terdiri dari konstanta lemah."

        # 5. Lain-lain
        else:
            reason = "Tipe assertion umum"

        has_msg = node.msg is not None

        # Penalti jika tidak ada pesan pada assertion kompleks
        if complexity > 1.5 and not has_msg:
            reason += " (Disarankan menambahkan pesan debugging)"

        return AssertionDetail(
            line_number=node.lineno,
            code_snippet=snippet,
            assertion_type=type(test_node).__name__,
            is_meaningful=is_meaningful,
            reason=reason,
            has_message=has_msg,
            involves_boolean_constant=involves_bool_const,
            complexity_score=complexity
        )

    def _calculate_complexity(self, node: ast.FunctionDef) -> float:
        """Menghitung skor kompleksitas sederhana berdasarkan struktur kontrol."""
        score = 1.0
        for child in ast.walk(node):
            if isinstance(child, (ast.If, ast.For, ast.While, ast.ExceptHandler)):
                score += 1.0
            elif isinstance(child, ast.BoolOp):
                score += 0.5 * len(child.values)
        return score

    def _get_line_snippet(self, lineno: int) -> str:
        if 0 < lineno <= len(self.source_lines):
            return self.source_lines[lineno - 1].strip()
        return ""

# ==============================================================================
# ENGINE UTAMA CHECKER
# ==============================================================================

class PytestQualityChecker:
    def __init__(self, target_path: str):
        self.target_path = Path(target_path)
        self.metrics = GlobalMetrics()
        self.file_results: list[FileAnalysisResult] = []

    def run(self) -> GlobalMetrics:
        """Menjalankan analisis pada seluruh direktori target."""
        if not self.target_path.exists():
            raise FileNotFoundError(f"Path tidak ditemukan: {self.target_path}")

        py_files = list(self.target_path.rglob("*.py"))
        # Filter file yang kemungkinan besar adalah file tes atau berada di folder 'tests'
        # Namun untuk analisis menyeluruh, kita scan semua tapi beri bobot lebih pada file tes
        test_files = [f for f in py_files if self._is_test_file(f)]

        # Jika tidak ada file tes terdeteksi secara nama, scan semua file python
        # untuk berjaga-jaga jika user menaruh tes di mana saja.
        if not test_files:
            test_files = py_files

        self.metrics.total_files_scanned = len(py_files)

        print(f"Memindai {len(test_files)} file potensial...")

        for file_path in test_files:
            result = self._analyze_single_file(file_path)
            self.file_results.append(result)

            # Agregasi metrik
            if result.error_during_analysis:
                continue

            if result.test_functions:
                self.metrics.total_test_files += 1
                self.metrics.total_test_functions += len(result.test_functions)

                # Hitung weighted tests (parametrized)
                weighted = sum(tf.parametrize_count for tf in result.test_functions)
                self.metrics.total_weighted_tests += weighted

                self.metrics.total_assertions += result.total_assertions
                self.metrics.total_meaningful_assertions += result.meaningful_assertions
                self.metrics.total_weak_assertions += result.weak_assertions

                neg_count = sum(1 for tf in result.test_functions if tf.has_negative_path)
                if neg_count > 0:
                    self.metrics.files_with_negative_path += 1
                self.metrics.total_negative_path_tests += neg_count

        self._calculate_final_scores()
        return self.metrics

    def _is_test_file(self, path: Path) -> bool:
        """Heuristik untuk mendeteksi file tes."""
        name = path.name
        parent = path.parent.name
        return (
            name.startswith('test_') or
            name.endswith('_test.py') or
            parent == 'tests' or
            'conftest' in name
        )

    def _analyze_single_file(self, filepath: Path) -> FileAnalysisResult:
        """Menganalisis satu file Python."""
        result = FileAnalysisResult(filepath=str(filepath), total_lines=0)

        try:
            content = filepath.read_text(encoding='utf-8')
            result.total_lines = len(content.splitlines())

            tree = ast.parse(content)
            analyzer = DeepTestAnalyzer(content)
            analyzer.visit(tree)

            result.test_functions = analyzer.test_functions

            # Hitung statistik assertion di level file
            for tf in result.test_functions:
                for ass in tf.assertions:
                    result.total_assertions += 1
                    if ass.is_meaningful:
                        result.meaningful_assertions += 1
                    else:
                        result.weak_assertions += 1

        except SyntaxError as e:
            result.error_during_analysis = f"Syntax Error: {e!s}"
        except Exception as e:
            result.error_during_analysis = f"Unexpected Error: {e!s}"
            logger.error(f"Gagal menganalisis {filepath}: {e}")

        return result

    def _calculate_final_scores(self):
        """Menghitung metrik agregat akhir."""
        if self.metrics.total_test_functions > 0:
            self.metrics.average_assertions_per_test = (
                self.metrics.total_assertions / self.metrics.total_test_functions
            )

        if self.metrics.total_assertions > 0:
            self.metrics.assertion_quality_score = (
                (self.metrics.total_meaningful_assertions / self.metrics.total_assertions) * 100
            )

        if self.metrics.total_weighted_tests > 0:
            self.metrics.negative_path_coverage = (
                (self.metrics.total_negative_path_tests / self.metrics.total_weighted_tests) * 100
            )

# ==============================================================================
# PELAPORAN & OUTPUT
# ==============================================================================

def get_weak_reason_summary(file_result: dict[str, Any]) -> str:
    """Mengembalikan ringkasan alasan kelemahan yang paling sering muncul di file."""
    reasons = []
    for detail in file_result.get('details', []):
        for assertion in detail.get('assertions', []):
            if not assertion.get('meaningful', True):
                reasons.append(assertion.get('reason', 'Unknown'))

    if not reasons:
        return ""

    # Hitung frekuensi
    counter = Counter(reasons)
    # Ambil 3 alasan teratas
    top = counter.most_common(3)
    summary = ", ".join([f"{reason} ({count}x)" for reason, count in top])
    return summary

def print_report(metrics: GlobalMetrics, top_n: int = 50):
    """Mencetak laporan berkualitas tinggi ke console."""
    print("\n" + "="*80)
    print(" LAPORAN ANALISIS KUALITAS PYTEST (REAL CODE ANALYSIS) ")
    print("="*80)

    print("\n📂 Cakupan Pemindaian:")
    print(f"   Total File Python: {metrics.total_files_scanned}")
    print(f"   File Tes Terdeteksi: {metrics.total_test_files}")

    print("\n🧪 Statistik Pengujian:")
    print(f"   Total Fungsi Tes: {metrics.total_test_functions}")
    print(f"   Total Kasus Uji (Weighted): {metrics.total_weighted_tests}")
    print(f"   Rata-rata Assertion per Tes: {metrics.average_assertions_per_test:.2f}")

    print("\n✅ Kualitas Assertion:")
    print(f"   Total Assertion: {metrics.total_assertions}")
    print(f"   Assertion Bermakna: {metrics.total_meaningful_assertions}")
    print(f"   Assertion Lemah (False Positives): {metrics.total_weak_assertions}")
    print(f"   SKOR KUALITAS: {metrics.assertion_quality_score:.2f}%")

    status_quality = "BAIK ✅" if metrics.assertion_quality_score >= THRESHOLD_ASSERTION_QUALITY else "PERLU PERBAIKAN ⚠️"
    print(f"   Status: {status_quality} (Threshold: {THRESHOLD_ASSERTION_QUALITY}%)")

    print("\n🛡️  Negative Path Coverage (Error Handling):")
    print(f"   Tes dengan Error Handling: {metrics.total_negative_path_tests}")
    print(f"   Cakupan: {metrics.negative_path_coverage:.2f}%")

    status_neg = "ADEKUAT ✅" if metrics.negative_path_coverage >= THRESHOLD_NEGATIVE_PATH_COVERAGE else "RENDAH ⚠️"
    print(f"   Status: {status_neg} (Threshold: {THRESHOLD_NEGATIVE_PATH_COVERAGE}%)")

    # Detail File dengan Assertion Lemah Terbanyak
    weak_files = sorted(
        [r for r in metrics.detailed_file_results.values() if r.get('weak_assertions', 0) > 0],
        key=lambda x: x['weak_assertions'],
        reverse=True
    )[:top_n]

    if weak_files:
        print(f"\n⚠️  Top {len(weak_files)} File dengan Assertion Lemah (dari {sum(1 for r in metrics.detailed_file_results.values() if r.get('weak_assertions',0)>0)} file):")
        print("   (Total Assertion, Weak, %Weak, Alasan Utama)")
        for idx, f in enumerate(weak_files, 1):
            total = f.get('total_assertions', 0)
            weak = f.get('weak_assertions', 0)
            pct = (weak / total * 100) if total > 0 else 0
            reason_summary = get_weak_reason_summary(f)
            print(f"   {idx:3}. {f['filepath']}")
            print(f"        Total: {total}, Weak: {weak} ({pct:.1f}%)")
            if reason_summary:
                print(f"        Alasan: {reason_summary}")
            else:
                print("        (Tidak ada alasan terperinci)")

    # Rekomendasi perbaikan
    print("\n" + "="*80)
    print(" 💡 REKOMENDASI PERBAIKAN")
    print("="*80)
    print("  1. Hindari assertion terhadap konstanta tetap (True, False, None, 0, 1, '', [], {}).")
    print("  2. Hindari perbandingan eksplisit dengan True/False (misal: assert result == True → cukup assert result).")
    print("  3. Tambahkan pesan debugging pada assertion kompleks untuk memudahkan pelacakan.")
    print("  4. Pastikan setiap tes memiliki setidaknya satu assertion yang bermakna.")
    print("  5. Periksa file-file dengan persentase weak assertions tinggi untuk refactoring.")

    print("="*80)

def export_json(metrics: GlobalMetrics, output_file: str = "pytest_report.json"):
    """Mengekspor hasil ke JSON untuk integrasi CI/CD."""
    # Konversi dataclass ke dict secara rekursif
    data = asdict(metrics)

    # Tambahkan timestamp
    data['generated_at'] = datetime.now().isoformat()
    data['version'] = "5.2.0"

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"💾 Laporan JSON disimpan ke: {output_file}")

# ==============================================================================
# ENTRY POINT
# ==============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Pytest Quality Analyzer - Analisis kualitas suite pengujian pytest",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Contoh: python pytest_checker.py ./tests --top 20 --json"
    )
    parser.add_argument('directory', help='Direktori target yang berisi file tes')
    parser.add_argument('--top', type=int, default=50, help='Jumlah file dengan assertion lemah terbanyak yang ditampilkan (default: 50)')
    parser.add_argument('--json', action='store_true', help='Ekspor laporan ke file JSON (pytest_report.json)')
    parser.add_argument('--output', type=str, default='pytest_report.json', help='Nama file output JSON (jika --json digunakan)')

    args = parser.parse_args()

    try:
        checker = PytestQualityChecker(args.directory)
        metrics = checker.run()

        # Populate detailed results for JSON export if needed
        # dan juga untuk laporan
        for res in checker.file_results:
            if not res.error_during_analysis:
                metrics.detailed_file_results[res.filepath] = {
                    'filepath': res.filepath,
                    'total_lines': res.total_lines,
                    'test_count': len(res.test_functions),
                    'total_assertions': res.total_assertions,
                    'meaningful_assertions': res.meaningful_assertions,
                    'weak_assertions': res.weak_assertions,
                    'details': [
                        {
                            'function': tf.name,
                            'parametrized_count': tf.parametrize_count,
                            'has_negative_path': tf.has_negative_path,
                            'assertions': [
                                {
                                    'line': a.line_number,
                                    'code': a.code_snippet,
                                    'meaningful': a.is_meaningful,
                                    'reason': a.reason
                                } for a in tf.assertions
                            ]
                        } for tf in res.test_functions
                    ]
                }

        print_report(metrics, top_n=args.top)

        if args.json:
            export_json(metrics, args.output)

    except Exception as e:
        print(f"❌ Fatal Error: {e}")
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
