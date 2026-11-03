"""Search, transaction classification, reviewed links and session management."""

from .date_display import display_dates
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLineEdit,
    QLabel,
    QFormLayout,
    QComboBox,
    QDialogButtonBox,
    QMessageBox,
    QInputDialog,
    QTabWidget,
    QWidget,
)
from .tables_v09 import DataTable
from .repository_v09 import RepositoryV09, reference
from .analysis_v09 import fee_candidates, recurring_candidates
from .jobs_v09 import run_job
from .storage_v09 import session_records, remove_session
from .persistence import atomic_json


class ClassificationDialog(QDialog):
    def __init__(self, repo, tx, parent=None):
        super().__init__(parent)
        self.repo, self.tx = repo, tx
        self.setWindowTitle("Buchung klassifizieren · Auswirkung prüfen")
        form = QFormLayout(self)
        form.addRow(QLabel(display_dates(f"{tx['date']} · {tx['account']} · {tx['amount']} {tx['currency']}\n{tx.get('purpose', '')}")))
        self.kind = QComboBox()
        self.kind.addItems(["BANK_BOOKING", "BUY", "SELL", "DIVIDEND", "INTEREST", "DEPOSIT", "WITHDRAWAL", "FEE", "TAX", "TRANSFER_IN", "TRANSFER_OUT"])
        self.kind.setCurrentText(tx["kind"])
        form.addRow("Buchungsart", self.kind)
        self.security = QLineEdit(tx.get("security", ""))
        form.addRow("Wertpapierkennung", self.security)
        self.quantity = QLineEdit(tx.get("quantity") or "")
        form.addRow("Stückzahl", self.quantity)
        self.reason = QLineEdit()
        form.addRow("Begründung / Beleg", self.reason)
        self.effect = QLabel()
        self.effect.setWordWrap(True)
        form.addRow(self.effect)
        purpose = (tx.get("purpose") or "").casefold()
        suggestions = [
            kind
            for words, kind in [
                (("dividende", "ausschüttung"), "DIVIDEND"),
                (("gutschrift zinsen", "zinsertrag"), "INTEREST"),
                (("kontoführungsgebühr", "transaktionsgebühr"), "FEE"),
            ]
            if any(w in purpose for w in words)
        ]
        if len(suggestions) == 1 and tx["kind"] == "BANK_BOOKING":
            suggested = suggestions[0]
            button = QPushButton("Textvorschlag prüfen: " + suggested)
            button.clicked.connect(lambda: self.kind.setCurrentText(suggested))
            form.addRow(button)
        self.kind.currentTextChanged.connect(self.preview)
        self.preview()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        form.addRow(buttons)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)

    def preview(self):
        kind = self.kind.currentText()
        mapping = {
            "BUY": "Erhöht die erwartete Stückzahl. Kaufbetrag wird als Anschaffung geführt.",
            "SELL": "Verringert die erwartete Stückzahl. Verkauf kann in die FIFO-Auswertung eingehen.",
            "DEPOSIT": "Erhöht die externen Zahlungsströme.",
            "WITHDRAWAL": "Wird als externer Abfluss ausgewertet.",
            "DIVIDEND": "Wird unter Ausschüttungen ausgewiesen.",
            "INTEREST": "Wird als Zinsertrag ausgewiesen.",
            "FEE": "Wird als separate Gebühr ausgewiesen.",
            "TAX": "Wird als separate Steuer ausgewiesen.",
            "BANK_BOOKING": "Bleibt unklassifiziert und damit im ungeklärten Rest.",
        }
        self.effect.setText(
            display_dates(
                f"Vorher: {self.tx['kind']} → Nachher: {kind}\n"
                + mapping.get(kind, "Wertpapierübertrag verändert die Stückzahl; nicht zusätzlich als Kapitalmaßnahme erfassen.")
                + "\nDie Originalbuchung bleibt erhalten."
            )
        )

    def save(self):
        try:
            from portfolio_v5.models import correction_number

            self.repo.classify(reference(self.tx), self.kind.currentText(), self.security.text(), correction_number(self.quantity.text()), self.reason.text())
            self.accept()
        except Exception as error:
            QMessageBox.warning(self, "Klassifikation", str(error))


class OperationsDialog(QDialog):
    def __init__(self, repo, account=None, parent=None):
        super().__init__(parent)
        self.repo, self.account = repo, account
        self.setWindowTitle("Buchungen und bestätigte Zuordnungen")
        self.resize(1200, 780)
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        self.panels = {}
        definitions = [
            (
                "bookings",
                "Buchungen",
                [("Klassifizieren", self.classify), ("Depotposition zuordnen", self.assign_portfolio), ("Klassifikation zurücknehmen", self.unclassify)],
            ),
            ("fees", "Gebührenabgleich", [("Belegverknüpfung bestätigen", self.confirm_fee)]),
            ("links", "Bestätigte Gebührenbelege", [("Verknüpfung zurücknehmen", self.revoke_fee)]),
            ("recurring", "Regelmäßige Zahlungen", [("Vorschlag bestätigen", self.confirm_recurring)]),
            ("actions", "Kapitalmaßnahmen", [("Maßnahme korrigieren", self.correct_action), ("Maßnahme zurücknehmen", self.revoke_action)]),
            ("security_transfers", "Wertpapierüberträge", [("Zuordnung zurücknehmen", self.revoke_security_transfer)]),
            ("transfers", "Umbuchungen", [("Verknüpfung zurücknehmen", self.revoke_transfer)]),
            ("rules", "Bestätigte Regelmäßigkeit", [("Regel entfernen", self.remove_rule)]),
            ("portfolio_rules", "Wertpapier-Zuordnungsregeln", [("Zuordnungsregel entfernen", self.remove_portfolio_rule)]),
        ]
        for key, title, buttons in definitions:
            panel = QWidget()
            box = QVBoxLayout(panel)
            table = DataTable()
            box.addWidget(table)
            self.panels[key] = table
            bar = QHBoxLayout()
            box.addLayout(bar)
            for label, callback in buttons:
                button = QPushButton(label)
                button.clicked.connect(lambda checked=False, f=callback: self.perform(f))
                bar.addWidget(button)
            self.tabs.addTab(panel, title)
        self.panels["actions"].view.doubleClicked.connect(lambda _index:self.open_source("actions"))
        self.panels["security_transfers"].view.doubleClicked.connect(lambda _index:self.open_source("security_transfers"))
        self.refresh()

    def open_source(self,key):
        from pathlib import Path
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        row=self.selected(key)
        candidates=([row.get('source','')] if key=='actions' else
                    [row['out_transaction'].get('source',''),row['in_transaction'].get('source','')])
        path=next((Path(value) for value in candidates if value and Path(value).is_file()),None)
        if path: QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve())))

    def set_data(self, key, headers, rows, payloads):
        table = self.panels[key]
        table.reset(headers, rows)
        table.payloads = {id(r): p for r, p in zip(rows, payloads)}

    def selected(self, key):
        table = self.panels[key]
        index = table.view.currentIndex()
        if not index.isValid():
            raise ValueError("Bitte zuerst eine Zeile auswählen.")
        return table.payloads[id(table.model.rows[index.row()])]

    def refresh(self):
        txs = self.repo.transactions(self.account)
        self.set_data(
            "bookings",
            ["Datum", "Konto", "Art", "Wertpapier", "Stück", "Betrag", "Währung", "Text", "Quelle"],
            [
                [
                    t["date"],
                    t["account"],
                    t["kind"],
                    t.get("security"),
                    t.get("quantity"),
                    Decimal(t["amount"]),
                    t["currency"],
                    t.get("purpose", ""),
                    t["source"],
                ]
                for t in txs
            ],
            txs,
        )
        fees = fee_candidates(self.repo, txs)
        self.set_data(
            "fees",
            ["Datum", "Konto", "Betrag", "Währung", "Nebenfeld", "Quelle Nebenfeld", "Separate Quelle"],
            [[r[k] for k in ("day", "account", "amount", "currency", "field", "source", "other_source")] for r in fees],
            fees,
        )
        valid_links = {(r["aux_ref"], r["field"]) for r in self.repo.fee_links()}
        links = self.repo.fee_links(include_invalid=True)
        self.set_data(
            "links",
            ["Status", "Nebenfeld", "Begründung", "Ursprungsbeleg", "Gebührenbeleg"],
            [
                ["Aktiv" if (r["aux_ref"], r["field"]) in valid_links else "Ungültig · prüfen oder zurücknehmen"]
                + [r[k] for k in ("field", "reason", "aux_ref", "fee_ref")]
                for r in links
            ],
            links,
        )
        candidates = recurring_candidates(self.repo)
        self.set_data(
            "recurring",
            ["Konto", "Beschreibung", "Betrag", "Währung", "Abstand Tage", "Belege"],
            [[r["account"], r["description"], r["amount"], r["currency"], r["interval_days"], len(r["refs"])] for r in candidates],
            candidates,
        )
        actions = [r for r in self.repo.actions("0001-01-01", "9999-12-31") if isinstance(r['id'],int)]
        self.set_data(
            "actions",
            ["Datum", "Depot", "Wertpapier", "Art", "Verhältnis", "Stück", "Kostenanteil", "Kostenminderung", "Quelle"],
            [[r.get(k) for k in ("day", "depot", "security", "kind", "ratio", "units", "cost_ratio", "cost_amount", "source")] for r in actions],
            actions,
        )
        security_pairs=self.repo.security_transfer_pairs()
        self.set_data("security_transfers",
            ["Bestätigt","Quell-Depot","Zieldepot","Wertpapier","Stück","Ausgang","Eingang","Begründung"],
            [[r['created_at'],r['out_transaction']['depot'],r['in_transaction']['depot'],r['out_transaction'].get('security'),
              r['out_transaction'].get('quantity'),r['out_transaction']['date'],r['in_transaction']['date'],r['note']] for r in security_pairs],security_pairs)
        valid_pairs = {r["id"] for r in self.repo.transfer_pairs()}
        pairs = self.repo.transfer_pairs(include_invalid=True)
        self.set_data(
            "transfers",
            ["Status", "Bestätigt am", "Begründung", "Ausgangsbeleg", "Gegenbeleg"],
            [
                ["Aktiv" if r["id"] in valid_pairs else "Ungültig · prüfen oder zurücknehmen", r["created_at"], r["note"], r["first_ref"], r["second_ref"]]
                for r in pairs
            ],
            pairs,
        )
        rules = [dict(r) for r in self.repo.db.execute("SELECT * FROM recurring_rules")]
        self.set_data(
            "rules",
            ["Konto", "Beschreibung", "Betrag", "Währung", "Abstand Tage", "Bestätigt am"],
            [[r[k] for k in ("account", "description", "amount", "currency", "interval_days", "confirmed_at")] for r in rules],
            rules,
        )
        portfolio_rules = self.repo.portfolio_assignment_rules()
        self.set_data(
            "portfolio_rules",
            ["Konto-ID", "Art", "Text enthält", "Wertpapier", "Depot-ID", "Begründung"],
            [[r[k] for k in ("account_key", "kind", "text_pattern", "security", "depot_key", "reason")] for r in portfolio_rules],
            portfolio_rules,
        )

    def perform(self, callback):
        try:
            callback()
            self.refresh()
        except Exception as error:
            QMessageBox.warning(self, "Bearbeitung", str(error))

    def reason(self):
        text, ok = QInputDialog.getText(self, "Begründung", "Beleg oder Grund angeben:")
        return text.strip() if ok else ""

    def classify(self):
        ClassificationDialog(self.repo, self.selected("bookings"), self).exec()

    def assign_portfolio(self):
        from .account_bookings_dialog import TransactionEditDialog

        TransactionEditDialog(self.repo, self.selected("bookings"), self, dividend=True).exec()

    def unclassify(self):
        self.repo.remove_classification(reference(self.selected("bookings")))

    def confirm_fee(self):
        r = self.selected("fees")
        reason = self.reason()
        if reason:
            self.repo.confirm_fee(r["aux_ref"], r["field"], r["fee_ref"], reason)

    def confirm_recurring(self):
        self.repo.confirm_recurring(self.selected("recurring"))

    def revoke_fee(self):
        r = self.selected("links")
        self.repo.revoke_fee(r["aux_ref"], r["field"])

    def correct_action(self):
        from .widgets_v09 import ActionsDialog

        ActionsDialog(self.repo, self, self.selected("actions")).exec()

    def revoke_action(self):
        r = self.selected("actions")
        reason = self.reason()
        if reason:
            self.repo.revoke_action(r["id"], reason)

    def revoke_transfer(self):
        r = self.selected("transfers")
        reason = self.reason()
        if reason:
            self.repo.revoke_transfer(r["id"], reason)

    def revoke_security_transfer(self):
        r=self.selected("security_transfers"); reason=self.reason()
        if reason: self.repo.revoke_security_transfer(r['id'],reason)

    def remove_rule(self):
        r = self.selected("rules")
        with self.repo.db:
            self.repo.db.execute("DELETE FROM recurring_rules WHERE id=?", (r["id"],))

    def remove_portfolio_rule(self):
        self.repo.remove_portfolio_assignment_rule(self.selected("portfolio_rules")["id"])


class SessionDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.setWindowTitle("Importsitzungen verwalten")
        self.resize(1000, 620)
        layout = QVBoxLayout(self)
        self.table = DataTable()
        layout.addWidget(self.table)
        self.note = QLabel("Fortsetzbare Sitzungen bleiben bei der Bereinigung erhalten. Verwerfen und Löschen gelten nur für die ausgewählte Sitzung.")
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        bar = QHBoxLayout()
        layout.addLayout(bar)
        for label, callback in [
            ("Fortsetzen", self.resume),
            ("Auf aktuellen Datenstand übertragen", self.rebase),
            ("Verwerfen", self.discard),
            ("Abgeschlossene / verworfene Auswahl löschen", self.remove),
        ]:
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, f=callback: self.perform(f))
            bar.addWidget(button)
        self.refresh()

    def refresh(self):
        self.records = session_records(self.window.data_folder)
        self.table.reset(
            ["Sitzung", "Status", "Größe MiB", "Zuletzt verwendet"],
            [[r["name"], r["status"], round(r["bytes"] / 1024**2, 2), datetime.fromtimestamp(r["modified"]).strftime("%d.%m.%Y %H:%M")] for r in self.records],
        )

    def selected(self):
        index = self.table.view.currentIndex()
        if not index.isValid():
            raise ValueError("Sitzung auswählen.")
        name = self.table.model.rows[index.row()][0]
        return next(r for r in self.records if r["name"] == name)

    def perform(self, callback):
        try:
            callback()
            self.refresh()
        except Exception as error:
            QMessageBox.warning(self, "Importsitzung", str(error))

    def resume(self):
        self.window.resume_import(str(Path(self.selected()["path"]) / "session.json"))

    def rebase(self):
        from .import_v09 import ImportSession

        record = self.selected()
        session = ImportSession.resume(self.window.repository.store.path, Path(record["path"]) / "session.json")
        fresh = run_job(self, self.window.repository.store.path, "Sitzung aktualisieren", lambda job: session.rebase())
        self.window.run_session(fresh)

    def discard(self):
        path = Path(self.selected()["path"])
        atomic_json(path / "discarded.json", {"at": datetime.now().isoformat()})

    def remove(self):
        remove_session(self.window.data_folder, self.selected()["path"])


class SearchDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.setWindowTitle("Globale Suche · Wertpapiere, Konten, Buchungen und Belege")
        self.resize(1150, 680)
        layout = QVBoxLayout(self)
        bar = QHBoxLayout()
        layout.addLayout(bar)
        self.query = QLineEdit()
        self.query.setPlaceholderText("Name, Kennung, Betrag oder Belegtext")
        bar.addWidget(self.query)
        go = QPushButton("Suchen")
        bar.addWidget(go)
        go.clicked.connect(self.search)
        self.query.returnPressed.connect(self.search)
        self.table = DataTable()
        layout.addWidget(self.table)
        self.note = QLabel("Bis zu 500 Treffer. Doppelklick öffnet die passende Detailansicht.")
        layout.addWidget(self.note)
        self.table.view.doubleClicked.connect(self.open)
        self.query.setFocus()

    def search(self):
        query = self.query.text().strip().casefold()
        if not query:
            return

        def work(job):
            repo = RepositoryV09(job.path, backups=False)
            try:
                rows = []
                for kind, items in [
                    ("Konto", [dict(name=n, account=n) for n in repo.accounts()]),
                    ("Position", repo.holdings()),
                    ("Buchung", repo.transactions()),
                    ("Beleg", repo.bank_documents()),
                ]:
                    for r in items:
                        if job.isInterruptionRequested():
                            return rows
                        if query in " ".join(str(v) for v in r.values()).casefold():
                            rows.append(dict(kind=kind, data=r))
                            if len(rows) >= 500:
                                return rows
                return rows
            finally:
                repo.close()

        try:
            self.results = run_job(self, self.window.repository.store.path, "Daten durchsuchen", work)
            rows = [
                [
                    x["kind"],
                    x["data"].get("account", ""),
                    x["data"].get("name") or x["data"].get("title") or x["data"].get("purpose") or x["data"].get("external_id", ""),
                    x["data"].get("date") or x["data"].get("as_of", ""),
                    x["data"].get("amount") or x["data"].get("value"),
                    x["data"].get("source", ""),
                ]
                for x in self.results
            ]
            self.table.reset(["Trefferart", "Konto", "Name / Text", "Datum", "Betrag / Wert", "Quelle"], rows)
            self.lookup = {id(r): x for r, x in zip(rows, self.results)}
        except Exception as error:
            self.note.setText(display_dates(str(error)))

    def open(self, index):
        x = self.lookup[id(self.table.model.rows[index.row()])]
        r = x["data"]
        from .widgets_v09 import EvidenceDialog, AccountDrill

        if x["kind"] == "Buchung":
            ClassificationDialog(self.window.repository, r, self).exec()
        elif x["kind"] == "Konto":
            AccountDrill(self.window.repository, (r["account"], "9999-12-31"), self).exec()
        else:
            EvidenceDialog(self.window.repository, r.get("key"), (r.get("account"), "9999-12-31"), self).exec()
