"""PortMan 09: isolated data, reviewed imports and explainable comparisons."""

import sys
from pathlib import Path

if __name__ == "__main__":
    project_directory = Path(__file__).resolve().parents[2]
    # Application code lives in ``src`` while the deliberately file-based PDF
    # plugins live at the project root.  A direct GUI launch needs both paths.
    sys.path.insert(0, str(project_directory))
    sys.path.insert(0, str(project_directory / "src"))
    from portman.startup import use_project_python, setup_logging

    use_project_python(__file__)
    setup_logging()
from PySide6.QtWidgets import QApplication, QMessageBox
from portman.gui.window_compat import project_root
from portman.gui.position_tables import ModelTablesMixin
from portman.gui.save_guard import SaveGuardMixin
from portman.gui.scope_toolbar import LatestScopeMixin
from portman.gui.lock_editable import LockEditableMixin
from portman.gui.window_shell import MainWindow as BaseMainWindow
from portman.gui.main_window_v09 import MainWindowV09Mixin


class MainWindow(MainWindowV09Mixin, SaveGuardMixin, LatestScopeMixin, LockEditableMixin, ModelTablesMixin, BaseMainWindow):
    pass


if __name__ == "__main__":
    app = QApplication.instance() or QApplication(sys.argv)
    try:
        import argparse

        parser = argparse.ArgumentParser()
        parser.add_argument("--portfolio")
        args = parser.parse_args()
        portfolio = args.portfolio
        root = project_root()
        if portfolio is None:
            from portman.portfolios import startup_portfolio

            selected = startup_portfolio(root)
            portfolio = None if selected == (root / "data/v09").resolve() else selected
        window = MainWindow(portfolio)
        if args.portfolio is not None:
            from portman.portfolios import set_startup_portfolio

            try:
                set_startup_portfolio(root, args.portfolio)
            except ValueError:
                pass
        window.show()
        app.exec()
    except Exception as error:
        QMessageBox.critical(None, "PortMan 09 konnte nicht starten", str(error))
        raise
