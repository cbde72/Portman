from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDialogButtonBox,
    QHeaderView, QLabel, QMessageBox, QTableWidget, QTableWidgetItem, QVBoxLayout)
from .import_combo_style import style_target_account_combo
import json


class ImportAssignmentDialog(QDialog):
    def __init__(self, repository, import_ids, parent=None):
        super().__init__(parent)
        self.repo = repository
        self.rows = []
        self.setWindowTitle('Importkonten nachträglich zuordnen')
        self.resize(1100, 520)
        layout = QVBoxLayout(self)
        note = QLabel('Zielkonto je Quelle auswählen. Die Änderung gilt für die ausgewählten Imports und ihre historischen Daten. Zurückgenommene Imports bleiben inaktiv. „Für künftig merken“ aktualisiert zusätzlich die Importregel.')
        note.setWordWrap(True)
        layout.addWidget(note)
        sources = repository.import_assignment_rows(import_ids)
        self.table = QTableWidget(len(sources), 5)
        self.table.setHorizontalHeaderLabels(['Import / Datei', 'Quellkonto', 'Bisheriges Konto', 'Zielkonto', 'Für künftig merken'])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        accounts = [r for r in repository.account_records() if r['active']]
        for index, source in enumerate(sources):
            for col, value in enumerate([f"{source['import_id']} · {Path(source['path']).name}", source['source_name'], source['target_name']]):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                self.table.setItem(index, col, item)
            combo = QComboBox()
            style_target_account_combo(combo)
            combo.addItem('Zuordnung beibehalten', None)
            for account in accounts:
                if source.get('required_kind') and json.loads(account['details']).get('kind') != source['required_kind']:
                    continue
                combo.addItem(account['name'], account['account_key'])
            self.table.setCellWidget(index, 3, combo)
            remember = QTableWidgetItem('')
            remember.setFlags(remember.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            remember.setCheckState(Qt.CheckState.Unchecked)
            self.table.setItem(index, 4, remember)
            self.rows.append((source, combo, remember))
        for column, width in [(1, 180), (2, 180), (3, 240), (4, 160)]:
            self.table.setColumnWidth(column, width)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setDefaultSectionSize(52)
        layout.addWidget(self.table)
        if not sources:
            layout.addWidget(QLabel('Diese Imports enthalten keine zuordenbaren Kontodaten.'))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText('Zuordnungen speichern')
        buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(bool(sources))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('Abbrechen')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self):
        changes = []
        for source, combo, remember in self.rows:
            target = combo.currentData()
            keep_rule = remember.checkState() == Qt.CheckState.Checked
            if target is None and not keep_rule:
                continue
            changes.append({'import_id': source['import_id'], 'source_key': source['source_key'],
                'target_key': target or source['target_key'], 'remember': keep_rule})
        try:
            self.repo.reassign_imports(changes)
        except Exception as error:
            QMessageBox.warning(self, 'Zuordnung nicht gespeichert', str(error))
            return
        super().accept()
