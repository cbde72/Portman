"""Review all transaction types and resolve every conflicting booking explicitly."""

import json
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QComboBox,
    QLineEdit,
    QPushButton,
    QDialogButtonBox,
    QLabel,
    QMessageBox,
    QSplitter,
    QScrollArea,
    QTextEdit,
    QFormLayout,
    QCheckBox,
    QWidget,
)
from .import_preview import ImportPreviewDialog
from .import_jobs import PreviewProxy
from .widgets_shared import populate
from .jobs_v09 import run_job
from PySide6.QtGui import QColor, QPainter, QPen


class ImportWizard(ImportPreviewDialog):
    def __init__(self, repo, session, summaries, parent=None):
        self.session = session
        self.decisions = dict(session.decisions)
        self._selected = None
        self._stage = 0
        self.selected_old = {k: v["old_ref"] for k, v in self.decisions.items() if v.get("old_ref")}
        super().__init__(PreviewProxy(repo, session.batches, summaries), session.batches, parent)
        self.setWindowTitle("PortMan 09 · Import prüfen")
        self.tabs = self.findChild(QTabWidget)
        self.buttons = self.findChild(QDialogButtonBox)
        self.next = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.next.setText("Weiter · Import prüfen")
        self.all_transactions = QTableWidget()
        self.tx_rows = []
        rows = []
        for i, b in enumerate(self.batches):
            if b.source_sheet == "PDF":
                continue
            for t in b.transactions:
                self.tx_rows.append((b.path, t.account, t.external_id))
                rows.append(["", b.path, t.account, t.date, getattr(t, "value_date", ""), t.kind, t.security, t.quantity, t.amount, t.currency])
        populate(self.all_transactions, ["Übernehmen", "Datei", "Konto", "Datum", "Valuta", "Art", "Wertpapier", "Stück", "Betrag", "Währung"], rows)
        for i in range(len(rows)):
            item = self.all_transactions.item(i, 0)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
        self.tabs.addTab(self.all_transactions, "Alle Buchungen · Auswahl")
        self.conflict_table = QTableWidget()
        self.tabs.addTab(self.conflict_table, "Überschneidungen · Entscheidungen")
        from .import_conflict_actions import install_conflict_actions

        install_conflict_actions(self)
        self.conflict_detail = QTableWidget()
        self.tabs.addTab(self.conflict_detail, "Feldvergleich")
        self.conflict_table.cellClicked.connect(self.show_conflict)
        choose = QPushButton("Gegenbeleg für ausgewählten Konflikt wählen")
        self.layout().addWidget(choose)
        choose.clicked.connect(self.choose_candidate)
        self.review = QTableWidget()
        self.tabs.addTab(self.review, "Gemeinsame Wirkung")
        self.detail_tables = {}
        for key, title in [("dated", "Historische Wirkung"), ("balances", "Saldenwirkung"), ("transaction_rows", "Ausgewählte Buchungen")]:
            table = QTableWidget()
            self.detail_tables[key] = table
            self.tabs.addTab(table, title)
        self.review_note = QLabel("Konten zuordnen und Auswahl prüfen. Danach zeigt die Zusammenfassung, was importiert wird.")
        self.review_note.setWordWrap(True)
        self.layout().insertWidget(0, self.review_note)
        save = QPushButton("Sitzung speichern und später fortsetzen")
        self.layout().addWidget(save)
        save.clicked.connect(self.save_session)
        self.table.itemChanged.connect(self.invalidate)
        self.mapping_table.itemChanged.connect(self.invalidate)
        self.all_transactions.itemChanged.connect(self.invalidate)
        for _, _, combo, _ in self.mapping_rows:
            combo.currentIndexChanged.connect(self.invalidate)
        if hasattr(self, "pdf_bookings_table"):
            self.pdf_bookings_table.itemChanged.connect(self.invalidate)
            self.install_pdf_evidence()
        self.extra_review = QCheckBox("Weitere Prüfdetails anzeigen")
        self.layout().addWidget(self.extra_review)
        self.extra_review.toggled.connect(self.toggle_review_details)
        self.toggle_review_details(False)
        for widget in (self.conflict_table, self.review):
            self.tabs.setTabVisible(self.tabs.indexOf(widget), False)
        if not self.tx_rows:
            self.tabs.setTabVisible(self.tabs.indexOf(self.all_transactions), False)
        # Restore reviewed account assignments when resuming a session.
        for i, source, combo, remember in self.mapping_rows:
            target = self.batches[i].account_assignments.get(source["key"])
            index = combo.findData(target) if target else -1
            if index >= 0:
                combo.setCurrentIndex(index)

    def toggle_review_details(self, visible):
        for table in [self.conflict_detail, *self.detail_tables.values()]:
            self.tabs.setTabVisible(self.tabs.indexOf(table), visible)

    def show_review_tab(self, widget):
        self.tabs.setTabVisible(self.tabs.indexOf(widget), True)
        self.tabs.setCurrentWidget(widget)

    def invalidate(self, *args):
        self._stage = 0
        self._selected = None
        self.next.setText("Weiter · Import prüfen")
        self.review.setRowCount(0)
        self.review_note.setText("Auswahl geändert. Wirkung erneut prüfen.")
        for table in self.detail_tables.values():
            table.setRowCount(0)

    def selected_batches(self):
        if self._selected is not None:
            return self._selected
        selected = super().selected_batches()
        excluded = {key for i, key in enumerate(self.tx_rows) if self.all_transactions.item(i, 0).checkState() != Qt.CheckState.Checked}
        for b in selected:
            b.transactions = [t for t in b.transactions if (b.path, t.account, t.external_id) not in excluded]
            if b.source_sheet == "PDF":
                original = next(x for x in self.batches if x.path == b.path)
                evidence = {t.external_id: e for t, e in zip(original.transactions, original.pdf_booking_evidence)}
                b.pdf_booking_evidence = [evidence.get(t.external_id, {}) for t in b.transactions]
        return selected

    def read_decisions(self):
        if not hasattr(self, "conflicts"):
            return self.decisions
        return {
            c["key"]: dict(
                action=self.conflict_table.cellWidget(i, 0).currentData(),
                reason=self.conflict_table.cellWidget(i, 1).text(),
                old_ref=self.selected_old.get(c["key"]),
            )
            for i, c in enumerate(self.conflicts)
        }

    def choose_candidate(self):
        from PySide6.QtWidgets import QInputDialog
        from .repository_v09 import reference

        row = self.conflict_table.currentRow()
        if row < 0 or not hasattr(self, "conflicts"):
            return
        conflict = self.conflicts[row]
        candidates = self.session.candidates(conflict["key"])
        labels = [
            f"{i + 1} · {t['date']} · {t['account']} · {t['amount']} {t['currency']} · {t['external_id']} · {t['source']}" for i, t in enumerate(candidates)
        ]
        label, ok = QInputDialog.getItem(self, "Gegenbeleg prüfen", "Für Ersetzung ausschließlich vorhandene Belege wählen:", labels, 0, False)
        if ok:
            chosen = candidates[labels.index(label)]
            conflict["old"] = chosen
            self.selected_old[conflict["key"]] = reference(chosen)
            self.show_conflict(row, 0)
            self.decisions_changed()

    def decisions_changed(self, *args):
        if self._stage == 2:
            self._stage = 1
            self.next.setText("Weiter · Zusammenfassung")
            self.review.setRowCount(0)

    def show_conflict(self, row, column):
        if not hasattr(self, "conflicts") or row >= len(self.conflicts):
            return
        c = self.conflicts[row]
        fields = [
            ("date", "Buchungsdatum"),
            ("value_date", "Valuta"),
            ("account", "Konto"),
            ("kind", "Art"),
            ("security", "Wertpapier"),
            ("quantity", "Stück"),
            ("amount", "Betrag"),
            ("currency", "Währung"),
            ("external_id", "Buchungskennung"),
        ]
        populate(
            self.conflict_detail,
            ["Feld", "Neue Buchung", "Vorhandene Buchung"],
            [[label, c["new"].get(k), c["old"].get(k)] for k, label in fields] + [["Quelle", c["source"], c["old"].get("source")]],
        )
        for i, (field, label) in enumerate(fields):
            if c["new"].get(field) != c["old"].get(field):
                for j in (1, 2):
                    self.conflict_detail.item(i, j).setBackground(QColor("#fff0bd"))
                    self.conflict_detail.item(i, j).setForeground(QColor("#222222"))

    def accept(self):
        try:
            if self._stage == 2:
                QDialog.accept(self)
                return
            if self._stage == 0:
                self._selected = self.selected_batches()
                if not self._selected:
                    raise ValueError("Mindestens eine Datei auswählen.")
                self.conflicts = run_job(self, self.session.live_path, "Überschneidungen suchen", lambda job: self.session.conflicts(self._selected))

                def description(t, source):
                    return (
                        " | ".join(str(t.get(k, "")) for k in ("date", "value_date", "account", "kind", "security", "quantity", "amount", "currency"))
                        + " | "
                        + source
                    )

                populate(
                    self.conflict_table,
                    [
                        "Entscheidung",
                        "Begründung bei Ersatz",
                        "Neue Buchung: Datum / Valuta / Konto / Art / Wertpapier / Stück / Betrag / Währung / Quelle",
                        "Vorhandene Buchung",
                    ],
                    [
                        ["", "", description(c["new"], c["source"]), f"Bis zu {c['candidate_count']} Treffer · " + description(c["old"], c["old"]["source"])]
                        for c in self.conflicts
                    ],
                )
                for i, c in enumerate(self.conflicts):
                    combo = QComboBox()
                    combo.addItem("Bitte entscheiden", None)
                    for label, key in [("Beide behalten", "keep"), ("Neue überspringen", "skip"), ("Alte ersetzen (Revision)", "replace")]:
                        if key != "replace" or c["old"]["import_id"] >= 0 or c["candidate_count"] > 1:
                            combo.addItem(label, key)
                    saved = self.decisions.get(c["key"], {})
                    combo.setCurrentIndex(max(0, combo.findData(saved.get("action"))))
                    reason = QLineEdit(saved.get("reason", ""))
                    self.conflict_table.setCellWidget(i, 0, combo)
                    self.conflict_table.setCellWidget(i, 1, reason)
                    combo.currentIndexChanged.connect(self.decisions_changed)
                    reason.textChanged.connect(self.decisions_changed)
                self.conflict_table.setColumnWidth(0, 190)
                self.conflict_table.setColumnWidth(2, 490)
                self.conflict_table.setColumnWidth(3, 490)
                self._stage = 1
                self.next.setText("Weiter · Zusammenfassung")
                if self.conflicts:
                    from .import_conflict_actions import ask_conflict_policy

                    ask_conflict_policy(self)
                    self.show_conflict(0, 0)
                    self.show_review_tab(self.conflict_table)
                    return
            self.decisions = self.read_decisions()
            data = run_job(self, self.session.live_path, "Importwirkung berechnen", lambda job: self.session.simulate(job, self._selected, self.decisions))
            populate(self.review, ["Depot", "Position", "Stück vorher", "Stück nachher", "Wert vorher", "Wert nachher"], data["changes"])
            for key, headers in [
                ("dated", ["Datum", "Depot", "Position", "Stück vorher", "Stück nachher", "Wert vorher", "Wert nachher"]),
                ("balances", ["Konto", "Saldo vorher", "Saldo nachher"]),
                ("transaction_rows", ["Datei", "Datum", "Konto", "Art", "Wertpapier", "Stück", "Betrag", "Währung"]),
            ]:
                populate(self.detail_tables[key], headers, data[key])
            self.review_note.setText(
                f"{len(data['results'])} Dateien · {data['transactions']} ausgewählte Buchungen. Zuordnungen und Auswirkungen sind geprüft. Mit „Jetzt importieren“ speichern oder die Auswahl ändern."
            )
            self.show_review_tab(self.review)
            self._stage = 2
            self.next.setText("Jetzt importieren")
        except Exception as error:
            QMessageBox.warning(self, "Import prüfen", str(error))

    def save_session(self):
        try:
            path = self.session.save(self.selected_batches(), self.read_decisions())
            self.session_saved = True
            QMessageBox.information(self, "Sitzung gespeichert", str(path))
            self.reject()
        except Exception as error:
            QMessageBox.warning(self, "Sitzung", str(error))

    def install_pdf_evidence(self):
        panel = QSplitter()
        editor = QWidget()
        editor_layout = QVBoxLayout(editor)
        fields = QTextEdit()
        fields.setReadOnly(True)
        editor_layout.addWidget(fields)
        form = QFormLayout()
        editor_layout.addLayout(form)
        edits = {}
        for c, title in ((3, "Datum TT.MM.JJJJ"), (4, "Valuta"), (5, "Betrag"), (6, "Buchungstext")):
            edits[c] = QLineEdit()
            form.addRow(title, edits[c])
        apply = QPushButton("Felder in die Buchung übernehmen")
        editor_layout.addWidget(apply)
        panel.addWidget(editor)
        selected = [None]

        def save_fields():
            if selected[0] is None:
                return
            for c, edit in edits.items():
                self.pdf_bookings_table.item(selected[0], c).setText(edit.text())
            self.pdf_bookings_table.item(selected[0], 0).setCheckState(Qt.CheckState.Checked)
            self.invalidate()

        apply.clicked.connect(save_fields)
        area = QScrollArea()
        page = QLabel()
        area.setWidget(page)
        area.setWidgetResizable(True)
        panel.addWidget(area)
        self.tabs.addTab(panel, "PDF · Felder und Originalseite")

        def show(row, column):
            entry = next((x for x in self.pdf_booking_rows if x[2] == row), None)
            if not entry:
                return
            bi, ti, _ = entry
            batch = self.batches[bi]
            selected[0] = row
            for c, edit in edits.items():
                edit.setText(self.pdf_bookings_table.item(row, c).text())
            evidence = batch.pdf_booking_evidence[ti] if ti < len(batch.pdf_booking_evidence) else {}
            fields.setPlainText(
                "\n".join(
                    f"{self.pdf_bookings_table.horizontalHeaderItem(c).text()}: {self.pdf_bookings_table.item(row, c).text()}"
                    for c in range(self.pdf_bookings_table.columnCount())
                    if self.pdf_bookings_table.item(row, c)
                )
                + "\n\n"
                + json.dumps(evidence, ensure_ascii=False, indent=2)
            )
            try:
                import pypdfium2 as pdfium

                regions = []
                if evidence.get("ocr"):
                    from portfolio_v5.pdf_ocr import ocr_page_regions

                    regions = run_job(
                        self,
                        self.session.live_path,
                        "OCR-Textstellen lokalisieren",
                        lambda job: ocr_page_regions(batch.path, max(0, int(evidence.get("page", 1)) - 1)),
                    )
                with pdfium.PdfDocument(batch.path) as document:
                    index = max(0, int(evidence.get("page", 1)) - 1)
                    with document[min(index, len(document) - 1)] as source:
                        bitmap = source.render(scale=1.25)
                        image = bitmap.to_pil().convert("RGB")
                        qimage = QImage(image.tobytes(), image.width, image.height, image.width * 3, QImage.Format.Format_RGB888).copy()
                        # Locate the extracted booking text in the native text layer when available.
                        textpage = source.get_textpage()
                        needle = str(evidence.get("text") or self.pdf_bookings_table.item(row, 6).text()).strip()
                        if needle:
                            search = textpage.search(needle[:40], match_case=False)
                            hit = search.get_next()
                            if hit:
                                index, count = hit
                                painter = QPainter(qimage)
                                painter.setPen(QPen(QColor("#e8a500"), 2))
                                painter.setBrush(QColor(255, 220, 0, 65))
                                for n in range(index, index + count):
                                    left, bottom, right, top = textpage.get_charbox(n)
                                    painter.drawRect(
                                        int(left * 1.25),
                                        int((source.get_height() - top) * 1.25),
                                        max(2, int((right - left) * 1.25)),
                                        max(2, int((top - bottom) * 1.25)),
                                    )
                                painter.end()
                            search.close()
                        textpage.close()
                        if regions:
                            import re

                            words = {w.casefold() for w in re.findall(r"\w{4,}", needle)}
                            painter = QPainter(qimage)
                            painter.setPen(QPen(QColor("#e8a500"), 2))
                            painter.setBrush(QColor(255, 220, 0, 65))
                            for region in regions:
                                if words & {w.casefold() for w in re.findall(r"\w{4,}", region["text"])}:
                                    left, top, right, bottom = region["box"]
                                    painter.drawRect(int(left * 1.25), int(top * 1.25), int((right - left) * 1.25), int((bottom - top) * 1.25))
                            painter.end()
                        page.setPixmap(QPixmap.fromImage(qimage))
                        bitmap.close()
            except Exception as error:
                page.clear()
                page.setText("Originalseite nicht darstellbar: " + str(error))
            self.tabs.setCurrentWidget(panel)

        self.pdf_bookings_table.cellDoubleClicked.connect(show)


class CsvProfileDialog(QDialog):
    FIELDS = [
        ("account", "Konto *"),
        ("date", "Datum *"),
        ("amount", "Betrag *"),
        ("value_date", "Valuta"),
        ("currency", "Währung"),
        ("kind", "Buchungsart"),
        ("security", "Wertpapier / ISIN"),
        ("quantity", "Stück"),
        ("fees", "Gebühren"),
        ("taxes", "Steuern"),
        ("purpose", "Verwendungszweck"),
        ("external_id", "Buchungskennung"),
    ]

    def __init__(self, repo, path, parent=None):
        super().__init__(parent)
        self.repo, self.path = repo, str(path)
        self.setWindowTitle("CSV-Assistent · Original und Interpretation")
        self.resize(1150, 800)
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        layout.addLayout(top)
        self.profiles = QComboBox()
        self.profiles.addItems(["Neues Profil"] + list(repo.csv_profiles()))
        top.addWidget(self.profiles)
        self.name = QLineEdit()
        self.name.setPlaceholderText("Profilname")
        top.addWidget(self.name)
        self.fields = {}
        form = QHBoxLayout()
        layout.addLayout(form)
        for key, label, values in [
            ("delimiter", "Trennzeichen", ["; ", ",", "\t", "|"]),
            ("encoding", "Kodierung", ["utf-8-sig", "cp1252", "utf-16"]),
            ("date_format", "Datumsformat", ["%d.%m.%Y", "%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"]),
            ("decimal", "Dezimal", [",", "."]),
            ("thousands", "Tausender", [". ", ",", ""]),
            ("currency", "Standardwährung", ["EUR", "USD", "GBP", "CHF"]),
        ]:
            combo = QComboBox()
            combo.setEditable(True)
            combo.addItems([v.strip() if v != "\t" else v for v in values])
            self.fields[key] = combo
            form.addWidget(QLabel(label))
            form.addWidget(combo)
        self.invert = QCheckBox("Vorzeichen umkehren")
        layout.addWidget(self.invert)
        self.mapping = QTableWidget(len(self.FIELDS), 2)
        self.mapping.setHorizontalHeaderLabels(["Feld", "CSV-Spalte"])
        layout.addWidget(self.mapping)
        self.mapping.setColumnWidth(0, 240)
        self.mapping.horizontalHeader().setStretchLastSection(True)
        self.preview = QTableWidget()
        layout.addWidget(self.preview)
        self.note = QLabel()
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        bar = QHBoxLayout()
        layout.addLayout(bar)
        for title, callback in [
            ("Spalten neu lesen", self.read_columns),
            ("Interpretation prüfen", self.check),
            ("Profil speichern und importieren", self.save),
        ]:
            button = QPushButton(title)
            button.clicked.connect(callback)
            bar.addWidget(button)
        self.profiles.currentTextChanged.connect(self.load)
        self.read_columns()

    def read_columns(self):
        import csv

        try:
            with Path(self.path).open(encoding=self.fields["encoding"].currentText(), newline="") as source:
                reader = csv.DictReader(source, delimiter=self.fields["delimiter"].currentText())
                columns = reader.fieldnames or []
                self.raw = []
                for i, row in enumerate(reader):
                    self.raw.append(row)
                    if i >= 19:
                        break
            old = {key: self.mapping.cellWidget(i, 1).currentText() for i, (key, label) in enumerate(self.FIELDS) if self.mapping.cellWidget(i, 1)}
            aliases = {
                "account": "Konto",
                "date": "Datum",
                "amount": "Betrag",
                "purpose": "Verwendungszweck",
                "security": "ISIN",
                "quantity": "Stück",
                "currency": "Währung",
                "external_id": "ID",
            }
            for i, (key, label) in enumerate(self.FIELDS):
                self.mapping.setItem(i, 0, QTableWidgetItem(label))
                combo = QComboBox()
                combo.addItems(["Nicht zugeordnet"] + columns)
                self.mapping.setCellWidget(i, 1, combo)
                value = old.get(key) or next((c for c in columns if c.casefold() in (key, aliases.get(key, "").casefold())), None)
                if value:
                    combo.setCurrentText(value)
            populate(self.preview, columns, [[row.get(c, "") for c in columns] for row in self.raw])
            self.note.setText("Originalwerte der ersten 20 Zeilen. Pflichtfelder zuordnen und Interpretation prüfen.")
            return True
        except Exception as error:
            self.note.setText(str(error))
            return False

    def profile_data(self):
        return {
            **{k: c.currentText() for k, c in self.fields.items()},
            "invert_sign": self.invert.isChecked(),
            "columns": {
                key: self.mapping.cellWidget(i, 1).currentText()
                for i, (key, label) in enumerate(self.FIELDS)
                if self.mapping.cellWidget(i, 1).currentIndex() > 0
            },
        }

    def check(self):
        from .import_v09 import parse_profile_csv

        try:
            if not self.read_columns():
                return False
            self.profile = self.profile_data()
            self.batch = run_job(self, self.repo.store.path, "CSV interpretieren", lambda job: parse_profile_csv(self.path, self.profile))
            rows = []
            for t in self.batch.transactions[:20]:
                raw = self.raw[t.row - 2] if t.row - 2 < len(self.raw) else {}
                for key, label in self.FIELDS:
                    if key in self.profile["columns"]:
                        rows.append([t.row, label, raw.get(self.profile["columns"][key]), getattr(t, key, None)])
            populate(self.preview, ["CSV-Zeile", "Feld", "Original", "Interpretiert"], rows)
            self.preview.resizeColumnsToContents()
            self.preview.horizontalHeader().setStretchLastSection(True)
            self.note.setText(
                "\n".join(self.batch.errors[:8])
                if self.batch.errors
                else f"{len(self.batch.transactions)} Buchungen erkannt. Beträge und Vorzeichen vor Übernahme prüfen."
            )
            return not self.batch.errors
        except Exception as error:
            self.note.setText(str(error))
            return False

    def load(self, name):
        p = self.repo.csv_profiles().get(name)
        if not p:
            return
        self.name.setText(name)
        for k, c in self.fields.items():
            c.setCurrentText(p.get(k, ""))
        self.invert.setChecked(p.get("invert_sign", False))
        self.read_columns()
        for i, (key, label) in enumerate(self.FIELDS):
            self.mapping.cellWidget(i, 1).setCurrentText(p.get("columns", {}).get(key, "Nicht zugeordnet"))

    def save(self):
        if not self.check():
            return
        try:
            self.repo.save_csv_profile(self.name.text(), self.profile)
            self.accept()
        except Exception as error:
            self.note.setText(str(error))
