import ast
from pathlib import Path
import subprocess
import sys

import portman_parsers.api


ROOT = Path(__file__).parents[2]
SOURCE = ROOT / "src" / "portman_parsers"


def imported_modules(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (item.name for item in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module


def test_parser_source_has_no_v09_or_pdf_lab_imports():
    imports = {module for path in SOURCE.rglob("*.py") for module in imported_modules(path)}
    assert not any(module.startswith(("portfolio_v5", "portman_pdf_lab", "portman.gui")) for module in imports)


def test_parser_source_excludes_blocked_plugins_and_discovery():
    source = "\n".join(path.read_text(encoding="utf-8") for path in SOURCE.rglob("*.py"))
    relative_modules = {path.relative_to(SOURCE).with_suffix("").as_posix() for path in SOURCE.rglob("*.py")}
    assert not any(name.endswith(("pbb_direkt", "baader_krypto")) for name in relative_modules)
    imports = {module for path in SOURCE.rglob("*.py") for module in imported_modules(path)}
    assert not any(module.endswith(("pbb_direkt", "baader_krypto")) for module in imports)
    assert "importlib.util" not in source


def test_importing_dtos_does_not_load_pdf_or_ocr_packages():
    code = ("import sys, portman_parsers.api; "
            "blocked={'pypdf','pymupdf','pypdfium2','rapidocr','onnxruntime'}; "
            "raise SystemExit(1 if blocked & set(sys.modules) else 0)")
    completed = subprocess.run([sys.executable, "-c", code], check=False, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr


def test_package_imports_in_clean_subprocess():
    completed = subprocess.run(
        [sys.executable, "-c", "import portman_parsers; import portman_parsers.api"],
        check=False, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr

