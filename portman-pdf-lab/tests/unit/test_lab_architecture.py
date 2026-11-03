import ast
from pathlib import Path


SOURCE = Path(__file__).parents[2] / "src" / "portman_pdf_lab"


def test_lab_has_no_v09_imports_and_uses_public_parser_packages():
    modules = set()
    for path in SOURCE.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(item.name for item in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module)
    assert not any(module.startswith(("portfolio_v5", "portman.gui", "pdf_plugins")) for module in modules)
    assert any(module.startswith("portman_parsers") for module in modules)

