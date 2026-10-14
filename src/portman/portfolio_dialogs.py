"""Portfolio creation and selective account transfer dialogs."""
import sys
import json
from pathlib import Path
from PySide6.QtCore import Qt, QProcess
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QCheckBox,
    QDialogButtonBox, QTableWidget, QTableWidgetItem, QComboBox, QPushButton, QFileDialog,
    QMessageBox, QInputDialog)
from .portfolios import (available_portfolios, create_portfolio, portfolio_name,
                         set_startup_portfolio, startup_portfolio)
from .portfolio_transfer import export_accounts, read_package, import_accounts
from .gui.window_compat import project_root
from .busy_indicator import busy_cursor
from .import_jobs import run_job
from .repository_v09 import RepositoryV09


class AccountTransferDialog(QDialog):
    def __init__(self, repo, package=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Konten und Depots importieren' if package else 'Konten und Depots exportieren')
        self.resize(1200, 540)
        self.package = package
        self.rows = package['accounts'] if package else [dict(key=r['account_key'], name=r['name'], details=json.loads(r['details']))
                                                       for r in repo.account_records() if r['active']]
        layout = QVBoxLayout(self)
        note = QLabel('Konten auswählen. Übertragen werden Kontodetails einschließlich IBAN, BIC und Konto- / Depotnummer, gespeicherte Buchungen, Depotstände und Salden mit Historie. '
                      'Original-PDFs, Zugangsdaten und Änderungsprotokolle sind nicht enthalten.')
        note.setWordWrap(True); layout.addWidget(note)
        link_note = QLabel('Für die Zuordnung eines Verrechnungskontos bitte Depot und Verrechnungskonto gemeinsam auswählen. Wird nur das Depot importiert, bleibt diese Zuordnung bei neu angelegten Depots leer.')
        link_note.setWordWrap(True); layout.addWidget(link_note)
        if package:
            hint = QLabel('Nicht vorhandene Konten und Depots werden beim Import automatisch mit ihren Kontodetails und Kennungen angelegt (Auswahl „Neu: …“). Sie können auch ein bestehendes Zielkonto wählen oder einen neuen Namen eingeben. Fehlende Kennungen werden ergänzt; abweichende Kennungen verhindern den Import. Weitere bestehende Kontodetails bleiben erhalten.')
            hint.setWordWrap(True); layout.addWidget(hint)
        self.table = QTableWidget(len(self.rows), 7 if package else 6)
        self.table.setHorizontalHeaderLabels(['Auswahl', 'Konto / Depot', 'Typ', 'IBAN', 'BIC', 'Konto- / Depotnummer'] + (['Zielkonto / neuer Name'] if package else []))
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        existing = [r for r in repo.account_records() if r['active']]
        self.targets = []
        for i, row in enumerate(self.rows):
            item = QTableWidgetItem(); item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked); self.table.setItem(i, 0, item)
            self.table.setItem(i, 1, QTableWidgetItem(row['name']))
            self.table.setItem(i, 2, QTableWidgetItem(row['details'].get('kind', 'Konto')))
            for column, field in enumerate(('iban', 'bic', 'number'), 3):
                value = str(row['details'].get(field) or '')
                cell = QTableWidgetItem(value); cell.setToolTip(value)
                self.table.setItem(i, column, cell)
            if package:
                combo = QComboBox(); combo.setEditable(True); combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
                combo.addItem('Neu: ' + row['name'], row['name'])
                for account in existing: combo.addItem(account['name'], account['name'])
                match = next((j + 1 for j, a in enumerate(existing) if a['name'].casefold() == row['name'].casefold()), 0)
                combo.setCurrentIndex(match); self.targets.append(combo); self.table.setCellWidget(i, 6, combo)
        self.table.setColumnWidth(0, 70); self.table.setColumnWidth(1, 280); self.table.setColumnWidth(2, 150)
        self.table.setColumnWidth(3, 230); self.table.setColumnWidth(4, 110); self.table.setColumnWidth(5, 170)
        self.table.horizontalHeader().setStretchLastSection(True); layout.addWidget(self.table)
        bar = QHBoxLayout()
        for label, state in [('Alle auswählen', Qt.CheckState.Checked), ('Keine auswählen', Qt.CheckState.Unchecked)]:
            button = QPushButton(label); button.clicked.connect(lambda checked=False, s=state: self.select_all(s)); bar.addWidget(button)
        layout.addLayout(bar)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('Abbrechen')
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Auswahl importieren' if package else 'Auswahl exportieren')
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); layout.addWidget(buttons)

    def select_all(self, state):
        for row in range(self.table.rowCount()): self.table.item(row, 0).setCheckState(state)

    def selection(self):
        result = {}
        for i, row in enumerate(self.rows):
            if self.table.item(i, 0).checkState() != Qt.CheckState.Checked: continue
            name = row['name']
            if self.package:
                combo = self.targets[i]
                name = combo.currentData() if combo.currentIndex() >= 0 and combo.currentText() == combo.itemText(combo.currentIndex()) else combo.currentText().strip()
                if not name: raise ValueError('Bitte einen Zielkontonamen eingeben.')
            result[row['key']] = name
        if not result: raise ValueError('Bitte mindestens ein Konto oder Depot auswählen.')
        return result

    def accept(self):
        try: self.selection()
        except ValueError as error: QMessageBox.warning(self, 'Auswahl prüfen', str(error)); return
        super().accept()


def launch_portfolio(window, folder):
    root = project_root()
    if Path(folder).resolve() == Path(window.data_folder).resolve():
        set_startup_portfolio(root, folder)
        window.raise_(); window.activateWindow(); return
    executable = Path(sys.executable)
    if executable.with_name('pythonw.exe').exists(): executable = executable.with_name('pythonw.exe')
    started, _ = QProcess.startDetached(str(executable), [str(root / 'src/Gui/PortMan_V09.py'), '--portfolio', str(folder)], str(root))
    if not started: raise ValueError('Das Portfolio konnte nicht geöffnet werden.')
    set_startup_portfolio(root, folder)


def new_portfolio(window):
    dialog = QDialog(window); dialog.setWindowTitle('Neues Portfolio')
    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel('Name für das getrennte Portfolio:'))
    name = QLineEdit(); name.setPlaceholderText('z. B. Anna oder Demo'); layout.addWidget(name)
    demo = QCheckBox('Mit erfundenen Demodaten beginnen'); layout.addWidget(demo)
    hint = QLabel('Eigene Konten, Einstellungen und Sicherungen. Das neue Portfolio öffnet sich in einem eigenen Fenster.')
    hint.setWordWrap(True); layout.addWidget(hint)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Portfolio erstellen')
    buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('Abbrechen')
    buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); layout.addWidget(buttons)
    if dialog.exec() != QDialog.DialogCode.Accepted: return
    folder = create_portfolio(project_root(), name.text(), demo.isChecked())
    launch_portfolio(window, folder)


def open_portfolio(window):
    rows = available_portfolios(project_root())
    name, ok = QInputDialog.getItem(window, 'Portfolio öffnen', 'Portfolio auswählen:', [r[0] for r in rows], 0, False)
    if ok: launch_portfolio(window, next(folder for label, folder in rows if label == name))


def choose_startup_portfolio(window):
    root = project_root()
    rows = available_portfolios(root)
    current = startup_portfolio(root)
    selected_index = next((index for index, (_, folder) in enumerate(rows)
                           if folder.resolve() == current.resolve()), 0)
    name, ok = QInputDialog.getItem(window, 'Startportfolio festlegen',
                                    'Beim nächsten Start automatisch öffnen:',
                                    [row[0] for row in rows], selected_index, False)
    if not ok:
        return
    folder = next(folder for label, folder in rows if label == name)
    set_startup_portfolio(root, folder)
    QMessageBox.information(window, 'Startportfolio gespeichert',
                            f'„{name}“ wird beim nächsten normalen Start automatisch geöffnet.')


def transfer_export(window):
    dialog = AccountTransferDialog(window.repository, parent=window)
    if dialog.exec() != QDialog.DialogCode.Accepted: return
    path, _ = QFileDialog.getSaveFileName(window, 'Kontenexport speichern', 'Konten.portman.json', 'PortMan-Konten (*.portman.json)')
    if not path: return
    with busy_cursor(): export_accounts(window.repository, dialog.selection(), path)
    QMessageBox.information(window, 'Export abgeschlossen', f'{len(dialog.selection())} Konten / Depots exportiert.')


def transfer_import(window):
    path, _ = QFileDialog.getOpenFileName(window, 'Kontenexport öffnen', '', 'PortMan-Konten (*.portman.json)')
    if not path: return
    package = read_package(path)
    dialog = AccountTransferDialog(window.repository, package, window)
    if dialog.exec() != QDialog.DialogCode.Accepted: return
    selection = dialog.selection()
    database_path = window.repository.store.path
    def execute(job):
        # The import is already atomic. Opening the worker with automatic backups
        # would copy the complete database twice and can dominate the operation.
        repo = RepositoryV09(database_path, backups=False)
        try:
            def update(current, total, text):
                if job.isInterruptionRequested():
                    raise ValueError('Import abgebrochen. Es wurden keine Änderungen gespeichert.')
                job.progress.emit(current, total)
                job.phase.emit(text)
            return import_accounts(repo, package, selection, update)
        finally:
            repo.close()
    result = run_job(window, database_path, 'Konten und Depots importieren', execute)
    window.refresh_scope_choices(); window.reload_portfolio()
    QMessageBox.information(window, 'Kontenimport', 'Diese Auswahl wurde bereits importiert.' if result['status'] == 'duplicate' else 'Ausgewählte Konten und Depots wurden importiert.')


def install_portfolio_menu(window):
    menu = window.menuBar().addMenu('Portfolio')
    window.portfolio_menu = menu
    for title, callback in [('Neues Portfolio …', new_portfolio), ('Portfolio öffnen …', open_portfolio),
                            ('Startportfolio festlegen …', choose_startup_portfolio),
                            ('Konten / Depots exportieren …', transfer_export), ('Konten / Depots importieren …', transfer_import)]:
        action = QAction(title, window)
        def run(checked=False, callback=callback):
            try: callback(window)
            except Exception as error: QMessageBox.warning(window, 'Portfolio', str(error))
        action.triggered.connect(run); menu.addAction(action)
    label = QLabel('Portfolio: ' + portfolio_name(window.data_folder))
    window.statusBar().addPermanentWidget(label)
