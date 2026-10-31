"""Wheel-only Phase 6 smoke check; run with an empty PYTHONPATH."""
from pathlib import Path
import os
import sys
import tempfile

from PySide6.QtWidgets import QApplication
from portman_parsers.api import PdfDocument, PdfPage
from portman_parsers.registry import default_registry
from portman_pdf_lab.storage import ReferenceRepository
from portman_pdf_lab.ui.main_window import MainWindow


titles = {
    "dividendengutschrift": "Abrechnung Dividendengutschrift",
    "ertragsgutschrift": "Abrechnung Ertragsgutschrift",
    "einloesung": "Abrechnung Einlösung",
    "kosteninformation_mifid_ii": "Kosteninformation zum Wertpapiergeschäft Produktkosten 1,00 EUR",
    "investment_ausschuettung": "Steuerliche Behandlung: Investment-Ausschüttung",
    "dividende_steuer_inland": "Steuerliche Behandlung: Inländische Dividende",
    "vorabpauschale": "Steuerliche Behandlung: Vorabpauschale Vorabpauschale EUR 1,00",
    "wertpapierkauf": "Wertpapierkauf",
    "wertpapierverkauf": "Wertpapierverkauf",
    "finanzreport": "Finanzreport Nr. 1",
}


def main() -> None:
    registry = default_registry()
    parsed = set()
    for index, (handler, title) in enumerate(titles.items()):
        document = PdfDocument(f"isolation-{index}", f"{index:x}" * 64,
                               (PdfPage(1, f"comdirect\n{title}\nStk. 1,000 DE0008474511\nZu Ihren Gunsten EUR 10,00"),))
        detection = registry.select(document)
        assert detection is not None and detection.handler_id == handler
        result = registry.parse(document, detection)
        assert result.handler_id == handler and result.evidence
        parsed.add(handler)
        if handler in {"kosteninformation_mifid_ii", "vorabpauschale"}:
            assert not result.events[0].cash_movements
    assert parsed == set(titles)

    # Keep this smoke directory: on Windows Qt/SQLite can retain a short-lived
    # file handle until process exit, making eager TemporaryDirectory cleanup flaky.
    directory = Path(tempfile.mkdtemp(prefix="portman-phase6-isolation-"))
    repository = ReferenceRepository(directory / "reference.sqlite")
    document_id = repository.register_document("doc", "a" * 64, None, "comdirect", "test")
    run_id = repository.save_run(document_id, "user.comdirect-ertraege", "wertpapierkauf", "2.0", "1.5.0", {}, (), 1)
    assert repository.run(run_id)["handler_id"] == "wertpapierkauf"
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    window = MainWindow(directory / "gui.sqlite")
    assert window.tabs.count() == 9
    window.close()
    app.processEvents()

    forbidden = ("portfolio_v5", "pdf_plugins", "portman.gui")
    assert not [name for name in sys.modules if name.startswith(forbidden)]
    roots = {Path(module.__file__).resolve() for module in sys.modules.values()
             if getattr(module, "__file__", None) and module.__name__.startswith(("portman_parsers", "portman_pdf_lab"))}
    assert roots and all("site-packages" in str(path) for path in roots), roots
    print("phase6 isolation: 10 handlers, sqlite, gui, wheel origins OK")


if __name__ == "__main__":
    main()
