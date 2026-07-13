
import ast
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
KERNEL_DIR = ROOT / "kernel"

EXCLUDED_DIRS = {"checker", "tests", "migrations", "__pycache__", ".git", "docs", "scripts", "deployment", "monitoring", "reports"}

def is_abstract_method(node):
    """Cek apakah fungsi didekorasi dengan @abstractmethod."""
    for dec in node.decorator_list:
        if isinstance(dec, ast.Name) and dec.id == "abstractmethod":
            return True
        if isinstance(dec, ast.Attribute) and dec.attr == "abstractmethod":
            return True
        # kadang decorator berbentuk @abc.abstractmethod
        if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and dec.func.attr == "abstractmethod":
            return True
    return False

def scan_file(file_path):
    """Parse satu file, kembalikan dict base_class -> {required, optional}"""
    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception:
        return {}
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return {}

    contracts = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            required = []
            optional = []
            has_abstract = False
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if is_abstract_method(item):
                        has_abstract = True
                        required.append(item.name)
                    else:
                        optional.append(item.name)
            if has_abstract:
                contracts[node.name] = {
                    "required": required,
                    "optional": optional
                }
    return contracts

def main():
    all_contracts = {}
    for py_file in KERNEL_DIR.rglob("*.py"):
        # Skip folder yang tidak relevan
        if any(part in EXCLUDED_DIRS for part in py_file.parts):
            continue
        # Skip file dengan nama tertentu
        if py_file.name.startswith(("test_", "conftest")) or py_file.name in {"__init__.py", "exceptions.py", "base.py"}:
            continue
        contracts = scan_file(py_file)
        all_contracts.update(contracts)

    if not all_contracts:
        print("# Tidak ditemukan base class dengan abstractmethod di kernel/")
        print("base_class_contracts: {}")
        return

    output = {"base_class_contracts": all_contracts}
    print(yaml.dump(output, default_flow_style=False, allow_unicode=True, sort_keys=False))

if __name__ == "__main__":
    main()
