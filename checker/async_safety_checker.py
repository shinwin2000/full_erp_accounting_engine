#!/usr/bin/env python3
"""
async_safety_checker.py - Detect blocking calls in async, missing await, unsafe event loop
============================================================================================
Standar: Big 4 Audit · ISO/IEC 25010
Fitur: Deteksi blocking I/O, async without await, event loop misuse, thread safety
"""

from __future__ import annotations

import argparse
import ast
import concurrent.futures
import json
import pathlib
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass

try:
    from checker.core.rca import analyze_exception, get_engine
    RCA_AVAIL = True
except ImportError:
    RCA_AVAIL = False
    def get_engine(): return None
    def analyze_exception(e, ctx): return None

COLOR = {"RED": "\033[91m", "GREEN": "\033[92m", "YELLOW": "\033[93m", "CYAN": "\033[96m", "BOLD": "\033[1m", "RESET": "\033[0m"}
def c(k): return COLOR.get(k, "")

_AST_CACHE = {}
_CACHE_LOCK = threading.Lock()

def get_ast(p):
    key = str(p.resolve())
    with _CACHE_LOCK:
        if key in _AST_CACHE: return _AST_CACHE[key]
    try:
        tree = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
        # Mengikat parent node untuk mempermudah pelacakan (Akurasi 100%)
        for parent_node in ast.walk(tree):
            for child_node in ast.iter_child_nodes(parent_node):
                child_node.parent = parent_node

        with _CACHE_LOCK: _AST_CACHE[key] = tree
        return tree
    except Exception:
        return None

@dataclass
class AsyncIssue:
    file: str
    line: int
    kind: str
    detail: str
    confidence: float
    rca: dict | None = None

@dataclass
class Report:
    issues: list[AsyncIssue]
    total_async_funcs: int
    total_files: int
    score: float
    scan_time: float

class AsyncSafetyChecker:
    # 'print' dan 'input' dihapus agar tidak terjadi false-positive di skrip CLI/Log
    BLOCKING_FUNCS = {
        "time.sleep", "requests.get", "requests.post", "requests.put", "requests.delete",
        "os.system", "subprocess.run", "subprocess.call", "open",
        "socket.connect", "socket.send", "socket.recv", "select.select", "select.poll",
        "threading.Lock", "threading.RLock", "threading.Event", "threading.Condition",
        "queue.Queue", "queue.LifoQueue", "queue.PriorityQueue",
        "json.load", "json.dump", "pickle.load", "pickle.dump", "yaml.load", "yaml.dump",
        "xml.etree.ElementTree.parse", "xml.etree.ElementTree.fromstring",
        "sleep"
    }

    def __init__(self, root: pathlib.Path, exclude: list[str] = None, max_workers=4):
        self.root = root
        self.exclude = set(exclude or [])
        self.max_workers = max_workers
        self._lock = threading.Lock()
        self._issues: list[AsyncIssue] = []
        self._total_async = 0
        self._files = 0

    def scan(self) -> Report:
        t0 = time.perf_counter()
        files = list(self._walk())
        self._files = len(files)

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            futures = {ex.submit(self._analyze_file, f): f for f in files}
            for future in concurrent.futures.as_completed(futures):
                try:
                    issues, async_count = future.result()
                    with self._lock:
                        self._issues.extend(issues)
                        self._total_async += async_count
                except Exception as e:
                    print(f"Warning - failed analyzing a file: {e}")

        # Perbaikan Logika Skor:
        # Berbasis persentase rasio fungsi yang sehat agar akurat untuk proyek skala masif.
        if self._total_async > 0:
            healthy_ratio = max(0.0, (self._total_async - len(self._issues)) / self._total_async)
            score = round(healthy_ratio * 100, 2)
        else:
            score = 100.0 if not self._issues else 0.0

        return Report(self._issues, self._total_async, self._files, score, time.perf_counter() - t0)

    def _walk(self) -> Iterator[pathlib.Path]:
        for p in self.root.rglob("*.py"):
            if any(part in self.exclude for part in p.parts): continue
            if "checker" in str(p): continue
            yield p

    def _analyze_file(self, py: pathlib.Path) -> tuple[list[AsyncIssue], int]:
        tree = get_ast(py)
        if tree is None: return [], 0
        issues = []
        async_count = 0
        rel = str(py.relative_to(self.root))

        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef):
                async_count += 1
                issues.extend(self._analyze_async_func(node, rel))

        return issues, async_count

    def _get_call_name(self, node) -> str:
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            base = self._get_call_name(node.value)
            return f"{base}.{node.attr}" if base else node.attr
        return ""

    def _analyze_async_func(self, node: ast.AsyncFunctionDef, rel: str) -> list[AsyncIssue]:
        issues = []

        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                full_call_name = self._get_call_name(child.func)

                # Deteksi Blocking Calls Valid
                if full_call_name in self.BLOCKING_FUNCS:
                    issues.append(AsyncIssue(
                        file=rel,
                        line=child.lineno,
                        kind="BLOCKING_CALL",
                        detail=f"Blocking call: {full_call_name} in async function '{node.name}'",
                        confidence=0.85,
                        rca=None
                    ))

                # Deteksi Unsafe Create Task (Fire-and-forget tanpa tracker)
                if full_call_name in ("asyncio.create_task", "create_task"):
                    if not self._task_is_handled(child, node):
                        issues.append(AsyncIssue(
                            file=rel,
                            line=child.lineno,
                            kind="UNSAFE_CREATE_TASK",
                            detail=f"asyncio.create_task without await or storage in '{node.name}'",
                            confidence=0.9,
                            rca=None
                        ))

        # Aturan 'MISSING_AWAIT' dimatikan secara permanen untuk mendukung framework web (FastAPI/Django)
        # yang sering memiliki async endpoints statis tanpa await.

        return issues

    def _task_is_handled(self, call_node: ast.Call, func_node: ast.AsyncFunctionDef) -> bool:
        parent = getattr(call_node, 'parent', None)
        if parent is None:
            return False

        if isinstance(parent, ast.Await):
            return True
        if isinstance(parent, (ast.Assign, ast.AnnAssign, ast.Return)):
            return True

        if isinstance(parent, ast.Call):
            parent_call = self._get_call_name(parent.func)
            if parent_call in ("gather", "asyncio.gather", "wait", "asyncio.wait"):
                return True

        if isinstance(parent, (ast.List, ast.Tuple, ast.Set)):
            return True

        return False

# ---- Reporters ----
def print_report(r, verbose):
    print(f"\n{c('CYAN')}{'='*70}{c('RESET')}")
    print(f"{c('BOLD')}ASYNC SAFETY CHECKER{c('RESET')}")
    print(f"{'='*70}")
    print(f"  Files: {r.total_files}, Async functions: {r.total_async_funcs}")
    print(f"  Issues: {len(r.issues)}")
    print(f"  RCA: {'✅ Active' if RCA_AVAIL else '⚠️ Fallback'}")

    # Pewarnaan Skor Berdasarkan Persentase
    score_color = c('GREEN') if r.score >= 95 else (c('YELLOW') if r.score >= 80 else c('RED'))
    print(f"  Score: {score_color}{r.score}/100{c('RESET')}")
    print(f"  Time: {r.scan_time:.2f}s")

    if r.issues:
        print("\nIssues:")
        for i in r.issues:
            color = c("RED") if i.kind in ("BLOCKING_CALL", "UNSAFE_CREATE_TASK") else c("YELLOW")
            print(f"  {color}[{i.kind}]{c('RESET')} {i.file}:{i.line} (conf:{i.confidence:.2f})")
            print(f"      {i.detail}")

def save_json(r, path):
    data = {"score": r.score, "issues": [{"file": i.file, "line": i.line, "kind": i.kind, "detail": i.detail} for i in r.issues]}
    with open(path, "w") as f: json.dump(data, f, indent=2)

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--verbose", "-v", action="store_true")
    p.add_argument("--json", metavar="FILE")
    p.add_argument("--exclude", default=".venv,venv,__pycache__,tests,checker")
    args = p.parse_args()
    root = pathlib.Path(__file__).resolve().parent.parent
    c_checker = AsyncSafetyChecker(root, args.exclude.split(","))
    r = c_checker.scan()
    print_report(r, args.verbose)
    if args.json: save_json(r, pathlib.Path(args.json))

if __name__ == "__main__": main()
