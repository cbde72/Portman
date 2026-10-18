"""Version eight analysis, guided corrections and recovery previews."""

from .date_display import display_dates
from .date_edit import DateLineEdit
import json
import tempfile
from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from PySide6.QtCore import Qt, QDate, QTimer, QUrl
from PySide6.QtGui import QAction, QKeySequence, QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QComboBox,
    QLineEdit,
    QFormLayout,
    QDateEdit,
    QTableWidget,
    QTabWidget,
    QMessageBox,
    QFileDialog,
    QDialogButtonBox,
    QAbstractItemView,
    QInputDialog,
)
from .widgets_shared import DashboardV07, EvidenceDialog as EvidenceV07, populate, amount
from .analysis_v09 import change_analysis, transfer_candidates, grouped_contributions
from .reports_v09 import export_report
from .repository_v09 import reference, RepositoryV09
from .jobs_v09 import run_job
from .persistence import atomic_json
from . import storage_v09 as storage


def table_tools(table):
    table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
    action = QAction("Für Excel kopieren", table)
    action.setShortcut(QKeySequence.StandardKey.Copy)
    action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
    table.addAction(action)

    def copy():
        indexes = table.selectionModel().selectedIndexes()
        if not indexes:
            return
        selected = {(i.row(), i.column()): str(i.data() or "") for i in indexes}
        rows = sorted({r for r, c in selected})
        cols = sorted({c for r, c in selected})

        # Neutralize spreadsheet formulas when copying text fields.
        def safe(text):
            return "'" + text if text.startswith(("=", "+", "@")) or text.startswith("-") and not text[1:2].isdigit() else text

        header = "\t".join(str(table.model().headerData(c, Qt.Orientation.Horizontal) or "") for c in cols)
        body = ["\t".join(safe(selected.get((r, c), "")).replace("\t", " ").replace("\n", " ") for c in cols) for r in rows]
        QApplication.clipboard().setText(display_dates(header + "\n" + "\n".join(body)))

    action.triggered.connect(copy)


class EvidenceDialog(EvidenceV07):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        back = QPushButton("Zurück zur vorherigen Auswahl")
        back.clicked.connect(self.accept)
        self.layout().addWidget(back)
        for table in self.findChildren(QTableWidget):
            table_tools(table)

    def open_source(self, path):
        if path and Path(path).is_file():
            return super().open_source(path)
        manifest = Path(self.repo.store.path).parent / "restored-sources" / "manifest.json"
        if manifest.exists():
            for source in json.loads(manifest.read_text(encoding="utf-8")).get("sources", []):
                if source["path"] == str(path) and source.get("included"):
                    candidate = manifest.parent / Path(source["entry"]).relative_to("sources")
                    if candidate.is_file():
                        QDesktopServices.openUrl(QUrl.fromLocalFile(str(candidate)))
                        return
        super().open_source(path)


class DashboardV09(DashboardV07):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        bar = QHBoxLayout()
        self.wealth_box.layout().addLayout(bar)
        button = QPushButton("Summen und Datenabdeckung erklären")
        button.clicked.connect(self.explain)
        bar.addWidget(button)
        drill = QPushButton("Konten und Belege öffnen")
        drill.clicked.connect(lambda: AccountDrill(self.repo, self.scope(), self).exec())
        bar.addWidget(drill)

    def refresh(self):
        if getattr(self.repo, "defer_initial_views", False):
            return
        super().refresh()
        holdings = self.repo.holdings(self.scope()[1], self.scope()[0])
        total = known = Decimal(0)
        missing_fx = 0
        for p in holdings:
            stamp = p.get("as_of") or p["period"] + "-01"
            rate = self.repo.historical_rate(p.get("currency", "EUR"), stamp)
            if rate is None or p.get("value") is None:
                missing_fx += 1
                continue
            weight = abs(Decimal(p["value"]) * rate)
            total += weight
            if p.get("cost") is not None and Decimal(p["cost"]) > 0:
                known += weight
        text = f"{known / total * 100:.1f} % des in EUR belegbaren Bestandswerts mit Einstand" if total else "Wertgewichtete Einstandsabdeckung unbekannt"
        if missing_fx:
            text += f" · {missing_fx} Positionen ohne Wert-/Währungsnachweis"
        self.cards["quality"].setText(display_dates(text))
        day = self.scope()[1]
        for key in ("cost", "pnl", "return"):
            self.cards[key].setToolTip(display_dates(text + " · Beträge nur für Positionen mit positivem Einstand."))
        for row, p in enumerate(sorted(holdings, key=lambda p: Decimal(p["value"] or 0), reverse=True)[:8]):
            status = "Belegt" if day == "9999-12-31" or p.get("as_of") == day else "Fortgeführt"
            for col in range(self.top.columnCount()):
                if self.top.item(row, col):
                    self.top.item(row, col).setToolTip(display_dates(f"{status} · Stand {p.get('as_of') or p['period']} · {p['source']}"))

    def open_position(self, row, column):
        positions = sorted(self.service.overview(self.scope()[1], self.scope()[0])["positions"], key=lambda p: Decimal(p["value"] or 0), reverse=True)[:8]
        if row < len(positions):
            EvidenceDialog(self.repo, positions[row]["key"], self.scope(), self).exec()

    def explain(self):
        account, day = self.scope()
        data = self.repo.wealth_summary(day, account)
        positions = self.repo.holdings(day, account)
        totals = defaultdict(Decimal)
        for p in positions:
            if p.get("value") is not None:
                totals[p["currency"]] += Decimal(p["value"])
        QMessageBox.information(
            self,
            "Warum unterscheiden sich Summen?",
            f"Dokumentiertes Vermögen: {amount(data['value'])}\nDepotbestände: "
            + ", ".join(f"{v} {c}" for c, v in totals.items())
            + "\nVermögen enthält Kontosalden, Altersvorsorge und Schulden. Depotansichten zeigen Positionen; Filter schränken diese weiter ein. Buchgewinne berücksichtigen nur bekannte Einstandswerte. Schätzungen verwenden andere Bewertungsstände.\n\n"
            + "\n".join(f"{r['account']}: {r['value']} · {r.get('effective_date', '')} · {r.get('source', '')}" for r in data.get("rows", [])),
        )


class AccountDrill(QDialog):
    def __init__(self, repo, scope, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Vermögen → Konten → Positionen → Belege")
        self.resize(1000, 620)
        self.repo, self.scope = repo, scope
        self.account = None
        self.saved = None
        layout = QVBoxLayout(self)
        self.note = QLabel("Doppelklick auf ein Konto öffnet Positionen und Buchungsbelege.")
        layout.addWidget(self.note)
        self.table = QTableWidget()
        layout.addWidget(self.table)
        table_tools(self.table)
        self.back = QPushButton("Zurück")
        layout.addWidget(self.back)
        self.back.clicked.connect(self.go_back)
        self.table.cellDoubleClicked.connect(self.open)
        self.accounts()

    def accounts(self):
        self.account = None
        self.rows = [r for r in self.repo.account_overview(self.scope[1]) if not self.scope[0] or r["name"] == self.scope[0]]
        populate(self.table, ["Konto", "Saldo", "Kategorie"], [[r["name"], r.get("balance"), r.get("categories")] for r in self.rows])

    def open(self, row, column):
        if self.account is None:
            self.saved = (row, self.table.verticalScrollBar().value())
            self.account = self.rows[row]["name"]
            self.positions = self.repo.holdings(self.scope[1], self.account)
            if not self.positions:
                EvidenceDialog(self.repo, None, (self.account, self.scope[1]), self).exec()
                self.go_back()
                return
            populate(
                self.table,
                ["Position", "Depot", "Stück", "Wert", "Währung", "Stand", "Quelle"],
                [[p["name"], p["depot"], p["quantity"], p["value"], p["currency"], p.get("as_of") or p["period"], p["source"]] for p in self.positions],
            )
        elif row < len(self.positions):
            EvidenceDialog(self.repo, self.positions[row]["key"], (self.account, self.scope[1]), self).exec()

    def go_back(self):
        if self.account is None:
            self.accept()
            return
        self.accounts()
        if self.saved:
            self.table.selectRow(self.saved[0])
            self.table.verticalScrollBar().setValue(self.saved[1])


class AnalysisDialog(QDialog):
    def __init__(self, repo, account=None, parent=None, start=None, end=None):
        super().__init__(parent)
        self.repo, self.account = repo, account
        self.data = None
        self.setWindowTitle("PortMan 09 · Veränderungen und Beiträge")
        self.resize(1180, 760)
        layout = QVBoxLayout(self)
        bar = QHBoxLayout()
        layout.addLayout(bar)
        self.start = QDateEdit(QDate.fromString(start, "yyyy-MM-dd") if start else QDate.currentDate().addYears(-1))
        self.end = QDateEdit(QDate.fromString(end, "yyyy-MM-dd") if end else QDate.currentDate())
        for editor in (self.start, self.end):
            editor.setCalendarPopup(True)
            editor.setDisplayFormat("dd.MM.yyyy")
            bar.addWidget(editor)
        self.export = QPushButton("Bericht exportieren")
        self.export.clicked.connect(self.export_data)
        bar.addWidget(self.export)
        self.group = QComboBox()
        for label, key in [
            ("Beiträge nach Konto", "account"),
            ("Beiträge nach Wertpapier", "name"),
            ("Beiträge nach Anlageklasse", "category"),
            ("Beiträge nach Währung", "currency"),
        ]:
            self.group.addItem(label, key)
        bar.addWidget(self.group)
        self.group.currentIndexChanged.connect(self.group_changed)
        self.note = QLabel()
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        self.tables = []
        from .tables_v09 import RowsModel, RowsView

        for name in (
            "Konten / Abdeckung",
            "Anlageklassen",
            "Positionen / Beiträge",
            "Stückzahlabstimmung",
            "Erträge / Gebühren / Steuern",
            "Zahlungsströme",
            "Kapitalmaßnahmen",
            "Gewinnbeiträge nach Anlageklasse",
            "Vermögensbrücke",
            "Realisierte Gewinne",
            "Beiträge vergleichen",
        ):
            table = RowsView()
            table.setModel(RowsModel())
            table.setAlternatingRowColors(True)
            table_tools(table)
            self.tables.append(table)
            self.tabs.addTab(table, name)
        self.tables[0].cellDoubleClicked.connect(self.account_evidence)
        for i in (2, 3):
            self.tables[i].cellDoubleClicked.connect(self.evidence)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(250)
        self._refresh_timer.timeout.connect(self.refresh)
        self.start.dateChanged.connect(self._queue_refresh)
        self.end.dateChanged.connect(self._queue_refresh)
        self.refresh()

    def _queue_refresh(self, *args):
        self._refresh_timer.start()

    def refresh(self):
        self.data = None
        self.export.setEnabled(False)
        for table in self.tables:
            table.model().reset(table.model().headers, [])
        try:
            self.data = change_analysis(self.repo, self.start.date().toString("yyyy-MM-dd"), self.end.date().toString("yyyy-MM-dd"), self.account)
        except ValueError as error:
            self.note.setText(display_dates(str(error)))
            return
        d = self.data
        self.export.setEnabled(True)
        self.note.setText(
            display_dates(
                f"{d['scope']} · gesamte Änderung {amount(d['change'])} · gleiche Kontenabdeckung {amount(d['comparable_change'])} ({d['comparable_accounts']} Konten). {d['unclassified']} unklassifizierte Buchungen. Keine Rendite. Unbekannt ≠ 0; Kurs-/FX-Beiträge in EUR nur mit belegbaren Währungen und Kursen."
            )
        )
        populate(
            self.tables[0],
            ["Konto", "Vorher (EUR)", "Nachher (EUR)", "Änderung (EUR)", "Abdeckung"],
            [[r["account"], amount(r["before"]), amount(r["after"]), amount(r["change"]), r["status"]] for r in d["accounts"]],
        )
        populate(
            self.tables[1],
            ["Anlageklasse", "Vorher (EUR)", "Nachher (EUR)", "Vergleichbare Änderung (EUR)"],
            [
                [
                    r["category"],
                    amount(r["before"]),
                    amount(r["after"]),
                    amount(r["comparable_after"] - r["comparable_before"]) if r["comparable_before"] is not None else "Unbekannt",
                ]
                for r in d["categories"]
            ],
        )
        populate(
            self.tables[2],
            ["Depot", "Position", "Vorher", "Nachher", "Änderung", "Währung", "Buchgewinnänderung", "Kursbeitrag EUR", "FX-Beitrag EUR"],
            [
                [
                    r["depot"],
                    r["name"],
                    r["before"],
                    r["after"],
                    r["change"],
                    r["currency"],
                    r["book_profit_change"],
                    amount(r["price_effect"]),
                    amount(r["fx_effect"]),
                ]
                for r in d["positions"]
            ],
        )
        populate(
            self.tables[3],
            ["Depot", "Position", "Anfang (Stück)", "Buchungen (Stück)", "Erwartet inkl. Maßnahmen", "Ende (Stück)", "Differenz", "Status"],
            [
                [r[k] for k in ("depot", "name", "opening_units", "booked_units", "expected_units", "closing_units", "difference", "status")]
                for r in d["positions"]
            ],
        )
        populate(
            self.tables[4],
            ["Monat", "Konto", "Wertpapier", "Art", "Währung", "Betrag"],
            [[r[k] for k in ("month", "account", "security", "kind", "currency", "amount")] for r in d["income"]],
        )
        populate(
            self.tables[5],
            ["Zahlungsstrom", "Betrag", "Währung"],
            [[k, v, "EUR"] for k, v in d["explained"].items()]
            + [["Bestätigte interne Umbuchungen", v, k] for k, v in d["internal"].items()]
            + [["Nicht eindeutig erklärt", d["residual"], "EUR"]],
        )
        populate(
            self.tables[6],
            ["Datum", "Depot", "Wertpapier", "Art", "Ziel", "Zieldepot", "Verhältnis", "Stück", "Quelle"],
            [[r[k] for k in ("day", "depot", "security", "kind", "target", "target_depot", "ratio", "units", "source")] for r in d["actions"]],
        )
        populate(
            self.tables[7],
            ["Anlageklasse", "Währung Buchgewinn", "Buchgewinnänderung", "Kursbeitrag EUR", "FX-Beitrag EUR", "Einstand belegt (Positionen)", "Positionen"],
            [
                [r[k] for k in ("category", "currency", "book_profit_change", "price_effect", "fx_effect", "known_profit_positions", "positions")]
                for r in d["contributions"]
            ],
        )
        populate(self.tables[8], ["Bestandteil", "Betrag EUR"], [[r["label"], amount(r["amount"])] for r in d["bridge"]])
        populate(
            self.tables[9],
            ["Datum", "Konto", "Wertpapier", "Währung", "Verkaufserlös", "FIFO-Einstand", "Realisierter Gewinn", "Angerechnete Vorabpauschale", "Steuerlicher Gewinn", "Methode / Abdeckung"],
            [[r[k] for k in ("date", "account", "security", "currency", "proceeds", "cost", "realized", "advance_tax_credit", "taxable_realized", "status")] for r in d["profit"]],
        )
        self.group_changed()
        q = d["quality"]
        self.note.setText(
            display_dates(
                self.note.text()
                + f" Abdeckung: Stückabstimmung {q['quantity_known']}/{q['positions']}, Kurs {q['price_known']}/{q['positions']}, FX {q['fx_known']}/{q['positions']}, Buchgewinn {q['profit_known']}/{q['positions']}. {len(d['fee_candidates'])} mögliche Gebühren-Doppelbelege benötigen Bestätigung."
            )
        )

    def group_changed(self, *args):
        if not self.data or len(self.tables) < 11:
            return
        rows = grouped_contributions(self.data, self.group.currentData())
        populate(
            self.tables[10],
            ["Gruppe", "Währung", "Wertänderung", "Unrealisierte Gewinnänderung", "Kursbeitrag EUR", "FX-Beitrag EUR", "Werte bekannt", "Positionen"],
            [[r[k] for k in ("group", "currency", "change", "book_profit_change", "price_effect", "fx_effect", "known", "total")] for r in rows],
        )

    def evidence(self, row, column):
        if self.data and row < len(self.data["positions"]):
            EvidenceDialog(self.repo, self.data["positions"][row]["key"], (self.account, self.end.date().toString("yyyy-MM-dd")), self).exec()

    def account_evidence(self, row, column):
        if self.data and row < len(self.data["accounts"]):
            AccountDrill(self.repo, (self.data["accounts"][row]["account"], self.end.date().toString("yyyy-MM-dd")), self).exec()

    def export_data(self):
        if not self.data:
            return
        path, selected = QFileDialog.getSaveFileName(self, "Auswertung speichern", "PortMan09-Auswertung", "Excel (*.xlsx);;HTML (*.html)")
        if path:
            if not Path(path).suffix:
                path += ".xlsx" if "xlsx" in selected else ".html"
            try:
                export_report(self.data, path)
            except Exception as error:
                QMessageBox.warning(self, "Export", str(error))


class CostDialog(QDialog):
    def __init__(self, repo, candidates, parent=None):
        super().__init__(parent)
        self.repo, self.candidates = repo, candidates
        self.setWindowTitle("Einstand anhand eines Belegs ergänzen")
        layout = QFormLayout(self)
        self.choice = QComboBox()
        self.choice.addItems([f"{p['depot']} · {p['name']} · {p.get('as_of') or p['period']}" for p in candidates])
        layout.addRow("Datenstand", self.choice)
        self.units = QLabel()
        layout.addRow("Belegte Stückzahl", self.units)
        self.cost = QLineEdit()
        layout.addRow("Gesamteinstand EUR (kein Stückpreis)", self.cost)
        self.source = QLineEdit()
        layout.addRow("Belegname und Datum", self.source)
        self.error = QLabel()
        layout.addRow(self.error)
        self.choice.currentIndexChanged.connect(self.update_units)
        self.update_units()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        layout.addRow(buttons)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)

    def update_units(self):
        self.units.setText(display_dates(str(self.candidates[self.choice.currentIndex()].get("quantity") or "Unbekannt")))

    def save(self):
        try:
            from portfolio_v5.models import correction_number

            p = self.candidates[self.choice.currentIndex()]
            self.repo.correct_cost(p["snapshot_id"], p["key"], correction_number(self.cost.text()), self.source.text())
            self.accept()
        except Exception as error:
            self.error.setText(display_dates(str(error)))


class ActionsDialog(QDialog):
    def __init__(self, repo, parent=None, action=None):
        super().__init__(parent)
        self.repo = repo
        self.setWindowTitle("Umbuchungen, Kapitalmaßnahmen und Währungskurse")
        self.resize(1050, 700)
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs)
        self.candidates = transfer_candidates(repo)
        table = QTableWidget()
        populate(
            table,
            ["Ausgang / Gegenbuchung", "Betrag", "Währung", "Ziel / Gegenbuchung", "Betrag"],
            [[f"{a['date']} · {a['account']}", a["amount"], a["currency"], f"{b['date']} · {b['account']}", b["amount"]] for a, b in self.candidates],
        )
        from PySide6.QtWidgets import QWidget

        panel = QWidget()
        box = QVBoxLayout(panel)
        box.addWidget(QLabel("Vorschläge werden erst nach ausdrücklicher Bestätigung als interne Umbuchung behandelt."))
        box.addWidget(table)
        note = QLineEdit()
        note.setPlaceholderText("Begründung / Beleg")
        box.addWidget(note)
        confirm = QPushButton("Ausgewähltes Paar bestätigen")
        box.addWidget(confirm)

        def pair():
            try:
                if table.currentRow() < 0:
                    raise ValueError("Paar auswählen.")
                a, b = self.candidates[table.currentRow()]
                repo.confirm_transfer(reference(a), reference(b), note.text())
                confirm.setEnabled(False)
                note.setText("Gespeichert. Weitere Paare nach erneutem Öffnen prüfen.")
            except Exception as error:
                QMessageBox.warning(self, "Umbuchung", str(error))

        confirm.clicked.connect(pair)
        tabs.addTab(panel, "Interne Umbuchungen")
        panel = QWidget()
        form = QFormLayout(panel)
        editors = {}
        for key, label, default in [
            ("day", "Datum TT.MM.JJJJ", date.today().isoformat()),
            ("depot", "Quell-Depot", ""),
            ("security", "Wertpapierkennung", ""),
            ("kind", "SPLIT / MERGER / TRANSFER", "SPLIT"),
            ("target", "Zielkennung (Fusion)", ""),
            ("target_depot", "Zieldepot (Übertrag)", ""),
            ("ratio", "Verhältnis neue / alte Stück", "1"),
            ("units", "Stück (Übertrag)", ""),
            ("sequence", "Reihenfolge (<1000000 vor Tagesbuchungen)", "0"),
            ("source", "Belegquelle", ""),
        ]:
            editors[key] = (DateLineEdit if key == "day" else QLineEdit)(str(action.get(key) or default) if action else default)
            form.addRow(label, editors[key])
        save = QPushButton("Kapitalmaßnahme erfassen")
        form.addRow(save)
        existing_action = action

        def save_action():
            try:
                data = {k: e.text() for k, e in editors.items()}
                data["units"] = data["units"] or None
                if existing_action:
                    repo.correct_action(existing_action["id"], **data)
                else:
                    repo.add_action(**data)
                save.setEnabled(False)
                self.accept()
            except Exception as error:
                QMessageBox.warning(self, "Kapitalmaßnahme", str(error))

        save.clicked.connect(save_action)
        tabs.addTab(panel, "Kapitalmaßnahme")
        if existing_action:
            tabs.setCurrentIndex(1)
        panel = QWidget()
        form = QFormLayout(panel)
        fx = {}
        for key, label in [
            ("day", "Datum TT.MM.JJJJ"),
            ("currency", "Währung, z. B. USD"),
            ("rate", "EUR je 1 Einheit Fremdwährung"),
            ("source", "Belegquelle"),
        ]:
            fx[key] = (DateLineEdit if key == "day" else QLineEdit)()
            form.addRow(label, fx[key])
        savefx = QPushButton("Historischen Kurs speichern")
        form.addRow(savefx)

        def rate():
            try:
                repo.save_fx(**{k: e.text() for k, e in fx.items()})
                self.accept()
            except Exception as error:
                QMessageBox.warning(self, "Wechselkurs", str(error))

        savefx.clicked.connect(rate)
        tabs.addTab(panel, "Historischer Wechselkurs")


class RecoveryDialog(QDialog):
    def __init__(self, repo, parent=None):
        super().__init__(parent)
        self.repo = repo
        self.restored = False
        self.setWindowTitle("PortMan 09 · Sicherungen und Wiederherstellung")
        self.resize(1050, 650)
        layout = QVBoxLayout(self)
        note = QLabel(
            "Manuelle Sicherungspunkte bleiben geschützt. Automatisch: letzte 6, dazu 7 Tages-, 8 Wochen- und 12 Monatsstände. Prüfungen laufen im Hintergrund. Pakete können Einstellungen und vertrauliche Originalbelege enthalten."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self.table = QTableWidget()
        layout.addWidget(self.table)
        bar = QHBoxLayout()
        layout.addLayout(bar)
        for title, callback in [
            ("Sicherungspunkt", self.backup),
            ("Alle prüfen", self.verify),
            ("Paket exportieren", self.package),
            ("Auswahl prüfen / öffnen", self.selected),
            ("Externe Sicherung", self.external),
        ]:
            button = QPushButton(title)
            button.clicked.connect(callback)
            bar.addWidget(button)
        self.refresh()

    def worker(self, title, function):
        def work(job):
            repo = RepositoryV09(job.path, backups=False)
            try:
                return function(repo, job)
            finally:
                repo.close()

        return run_job(self, self.repo.store.path, title, work)

    def refresh(self, records=None):
        self.records = records if records is not None else storage.backup_records(self.repo.backup_folder)
        populate(
            self.table,
            ["Bezeichnung", "Erstellt UTC", "Geschützt", "Prüfung", "Datei"],
            [[r.get("label"), r.get("created"), r.get("protected"), r["status"], r["path"]] for r in self.records],
        )
        if not hasattr(self, "status_note"):
            self.status_note = QLabel()
            self.status_note.setWordWrap(True)
            self.layout().insertWidget(1, self.status_note)
        status = storage.verification_status(self.repo.store.path.parent)
        self.status_note.setText(
            display_dates(
                f"Letzte Sicherung: {status['last_backup']} · Letzte Integritäts-/Wiederherstellungsprüfung: {status['last_verification']} · {status['free_bytes'] / 1024**3:.1f} GiB frei · {status['verification']}"
            )
        )

    def backup(self):
        name, ok = QInputDialog.getText(self, "Geschützter Sicherungspunkt", "Bezeichnung:")
        if ok:
            try:
                self.worker("Sicherung erstellen", lambda repo, job: repo.backup(label=name))
                self.refresh()
            except Exception as error:
                QMessageBox.warning(self, "Sicherung", str(error))

    def verify(self):
        try:
            records = run_job(
                self, self.repo.store.path, "Sicherungen prüfen", lambda job: storage.backup_records(self.repo.backup_folder, verify=True, job=job)
            )
            latest = next((r["path"] for r in records if r["status"] == "OK"), None)
            if latest:
                run_job(self, self.repo.store.path, "Wiederherstellung in Testumgebung", lambda job: storage.test_restore(latest))
            atomic_json(
                self.repo.store.path.parent / "backup-verification.json",
                {
                    "checked": datetime.now(timezone.utc).isoformat(),
                    "result": "Geprüft; letzte intakte Sicherung testweise geöffnet" if latest else "Keine intakte Sicherung vorhanden",
                },
            )
            self.refresh(records)
        except Exception as error:
            QMessageBox.warning(self, "Prüfung", str(error))

    def package(self):
        path, selected = QFileDialog.getSaveFileName(self, "Sicherungspaket speichern", "PortMan09", "Verschlüsselt (*.pm9);;ZIP (*.zip)")
        if not path:
            return
        encrypted = "pm9" in selected
        if not Path(path).suffix:
            path += ".pm9" if encrypted else ".zip"
        include = QMessageBox.question(self, "Originalbelege", "Vorhandene lokale Originalbelege in das Paket aufnehmen?") == QMessageBox.StandardButton.Yes
        credentials = (
            QMessageBox.question(
                self,
                "Lokale Bankzugänge",
                "Auch lokale Bankkonfigurationen aufnehmen? Verschlüsselte Windows-Zugänge können an diesen Benutzer gebunden bleiben.",
            )
            == QMessageBox.StandardButton.Yes
        )
        password = ""
        if encrypted:
            password, ok = QInputDialog.getText(self, "Paket verschlüsseln", "Passwort (mindestens 10 Zeichen):", QLineEdit.EchoMode.Password)
            if not ok:
                return

        def pack(repo, job):
            if not encrypted:
                return storage.export_package(repo.db, repo.store.path.parent, path, include, job, credentials)
            from .package_crypto_v09 import encrypt

            with tempfile.TemporaryDirectory() as folder:
                archive = Path(folder) / "package.zip"
                storage.export_package(repo.db, repo.store.path.parent, archive, include, job, credentials)
                encrypt(archive, path, password)
            return str(path)

        try:
            self.worker("Sicherungspaket erstellen", pack)
            QMessageBox.information(self, "Sicherungspaket", "Paket erstellt: " + path)
        except Exception as error:
            QMessageBox.warning(self, "Sicherungspaket", str(error))

    def selected(self):
        if self.table.currentRow() >= 0:
            self.restore_path(self.records[self.table.currentRow()]["path"])

    def external(self):
        path, _ = QFileDialog.getOpenFileName(self, "Sicherung wählen", "", "PortMan (*.sqlite *.zip *.pm9)")
        if path:
            self.restore_path(path)

    def restore_path(self, path):
        try:
            with tempfile.TemporaryDirectory() as folder:
                if Path(path).suffix.lower() == ".pm9":
                    password, ok = QInputDialog.getText(self, "Paket öffnen", "Passwort:", QLineEdit.EchoMode.Password)
                    if not ok:
                        return
                    from .package_crypto_v09 import decrypt

                    opened = Path(folder) / "opened.zip"
                    run_job(self, self.repo.store.path, "Paket entschlüsseln", lambda job: decrypt(path, opened, password))
                    path = opened
                candidate = run_job(self, self.repo.store.path, "Sicherung prüfen und Kopie vorbereiten", lambda job: storage.prepare_restore(path, folder))
                current = storage.inspect_database(self.repo.store.path)
                incoming = storage.inspect_database(candidate)
                preview = QDialog(self)
                preview.setWindowTitle("Wiederherstellung vorab prüfen")
                layout = QVBoxLayout(preview)
                table = QTableWidget()
                populate(
                    table, ["Datenbereich", "Aktuell", "Sicherung", "Differenz"], [[k, current[k], incoming[k], incoming[k] - current[k]] for k in current]
                )
                layout.addWidget(table)
                differences = run_job(
                    self,
                    self.repo.store.path,
                    "Inhaltliche Unterschiede ermitteln",
                    lambda job: storage.content_diff(self.repo.store.path, candidate, self.repo.store.path.parent, folder),
                )
                from .tables_v09 import DataTable

                details = DataTable(["Bereich", "Kennung", "Änderung", "Aktuell", "Sicherung"], differences["rows"])
                layout.addWidget(details)
                layout.addWidget(QLabel(display_dates(f"{differences['total']} inhaltliche Änderungen · angezeigt: {len(differences['rows'])}")))
                open_copy = QPushButton("Datenkopie öffnen · Belege und Konten")
                layout.addWidget(open_copy)

                def inspect():
                    copy = RepositoryV09(candidate, backups=False)
                    try:
                        AccountDrill(copy, (None, "9999-12-31"), preview).exec()
                    finally:
                        copy.close()

                open_copy.clicked.connect(inspect)
                layout.addWidget(QLabel("Aktueller Datenstand wird durch die geprüfte Kopie ersetzt. Zuvor entsteht ein geschützter Sicherungspunkt."))
                buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Cancel)
                layout.addWidget(buttons)
                buttons.button(QDialogButtonBox.StandardButton.Apply).setText("Geprüften Stand wiederherstellen")
                buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(preview.accept)
                buttons.rejected.connect(preview.reject)
                if preview.exec() != 1:
                    return
                self.worker("Datenstand wiederherstellen", lambda repo, job: storage.restore_prepared(repo.db, folder, repo.store.path.parent))
                self.restored = True
                self.accept()
        except Exception as error:
            QMessageBox.warning(self, "Wiederherstellung", str(error))
