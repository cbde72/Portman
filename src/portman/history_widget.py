from .date_display import display_dates
import json
from datetime import date
from pathlib import Path
from PySide6.QtCore import QDate, Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView,QCheckBox,QDateEdit,QDialog,QDialogButtonBox,QHBoxLayout,QLabel,
 QMessageBox,QLineEdit,QPushButton,QTabWidget,QTableWidget,QTableWidgetItem,QTreeWidget,QTreeWidgetItem,
 QVBoxLayout,QWidget,QPlainTextEdit,QFileDialog)
from .safe_canvas import SafeFigureCanvas
from portfolio_v5.performance import security_performance
from .chart_style import COLORS, PALETTE, compact_number, currency_axis, date_axis, style_axis, style_figure, create_figure
from .formatting import euro as _format_euro

def euro(v): return _format_euro(v, empty='')
def table(headers):
    w=QTableWidget(0,len(headers));w.setHorizontalHeaderLabels(headers);w.setAlternatingRowColors(True);return w
def fill(w,rows):
    if hasattr(w,'set_rows'): w.set_rows(list(rows)); return
    w.setSortingEnabled(False);w.setRowCount(len(rows))
    for r,row in enumerate(rows):
        for c,value in enumerate(row):
            item=QTableWidgetItem();item.setData(Qt.ItemDataRole.DisplayRole,display_dates(value));w.setItem(r,c,item)
    w.resizeColumnsToContents();w.setSortingEnabled(True)


class JsonReportDialog(QDialog):
    """Readable tree and complete source view for an import report."""
    def __init__(self, import_id, report, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f'Import {import_id} · Details')
        self.resize(920, 680)
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs)

        self.tree = QTreeWidget()
        self.tree.setObjectName('import_report_tree')
        self.tree.setHeaderLabels(['Feld', 'Wert', 'Typ'])
        self.tree.setAlternatingRowColors(True)
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tree.setUniformRowHeights(True)
        self._add_children(self.tree, report)
        self.tree.expandToDepth(1)
        self.tree.resizeColumnToContents(0)
        self.tree.setColumnWidth(1, 520)
        tabs.addTab(self.tree, 'Struktur')

        self.raw = QPlainTextEdit(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        self.raw.setObjectName('import_report_json')
        self.raw.setReadOnly(True)
        self.raw.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        tabs.addTab(self.raw, 'JSON')

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @classmethod
    def _add_children(cls, parent, value):
        entries = value.items() if isinstance(value, dict) else enumerate(value) if isinstance(value, list) else ()
        for key, child in entries:
            label = str(key) if isinstance(value, dict) else f'[{key}]'
            if isinstance(child, dict):
                item = QTreeWidgetItem([label, f'{len(child)} Felder', 'Objekt'])
            elif isinstance(child, list):
                item = QTreeWidgetItem([label, f'{len(child)} Einträge', 'Liste'])
            else:
                type_name = ('Leerwert' if child is None else 'Ja/Nein' if isinstance(child, bool)
                             else 'Zahl' if isinstance(child, (int, float)) else 'Text')
                display = ('–' if child is None else 'Ja' if child is True else 'Nein' if child is False else str(child))
                item = QTreeWidgetItem([label, display, type_name])
                item.setToolTip(1, display)
            parent.addTopLevelItem(item) if isinstance(parent, QTreeWidget) else parent.addChild(item)
            if isinstance(child, (dict, list)):
                cls._add_children(item, child)

class HistoryWidget(QWidget):
    data_changed=Signal()
    def __init__(self,repository,account_getter,parent=None):
        super().__init__(parent);self.repo=repository;self.account_getter=account_getter
        layout=QVBoxLayout(self);self.tabs=QTabWidget();layout.addWidget(self.tabs)
        wealth=QWidget();wl=QVBoxLayout(wealth);opts=QHBoxLayout();self.ret=QCheckBox('Altersvorsorge');self.prop=QCheckBox('Immobilie');self.debt=QCheckBox('Schulden abziehen')
        for x in (self.ret,self.prop,self.debt):x.stateChanged.connect(self.refresh_wealth);opts.addWidget(x)
        opts.addStretch();wl.addLayout(opts);self.fig=create_figure();style_figure(self.fig);self.canvas=SafeFigureCanvas(self.fig);self.canvas.setMinimumHeight(300);wl.addWidget(self.canvas);self.wealth_table=table(['Monat','Gesamt','Liquidität','Festgeld','Wertpapiere','Altersvorsorge','Immobilie','Schulden']);wl.addWidget(self.wealth_table);self.tabs.addTab(wealth,'Vermögen')
        compare=QWidget();cl=QVBoxLayout(compare);bar=QHBoxLayout();self.start=QDateEdit(QDate(2026,1,1));self.end=QDateEdit(QDate.currentDate());self.start.setCalendarPopup(True);self.end.setCalendarPopup(True);self.start.setDisplayFormat('dd.MM.yyyy');self.end.setDisplayFormat('dd.MM.yyyy');go=QPushButton('Vergleichen');go.clicked.connect(self.refresh_compare)
        for x in (QLabel('Von'),self.start,QLabel('Bis'),self.end,go):bar.addWidget(x)
        bar.addStretch();cl.addLayout(bar);self.diff=table(['Depot','Kennung','Name','Vorher','Nachher','Änderung','Stückänderung','Status']);cl.addWidget(self.diff);self.tabs.addTab(compare,'Vergleich')
        tx=QWidget();tl=QVBoxLayout(tx);tb=QHBoxLayout();confirm=QPushButton('Zeitraum vollständig');confirm.clicked.connect(self.confirm);calc=QPushButton('XIRR berechnen');calc.clicked.connect(self.performance);self.result=QLabel()
        for x in (confirm,calc,self.result):tb.addWidget(x)
        tb.addStretch();tl.addLayout(tb)
        self.tx_search = QLineEdit()
        self.tx_search.setPlaceholderText('Alle Buchungen durchsuchen …')
        self.tx_search.setClearButtonEnabled(True)
        # Typing must not reload every booking from the database; keep the rows
        # cached and only re-filter after a short pause.
        self._tx_rows = None
        self._tx_filter_timer = QTimer(self)
        self._tx_filter_timer.setSingleShot(True)
        self._tx_filter_timer.setInterval(150)
        self._tx_filter_timer.timeout.connect(self.apply_transaction_filter)
        self.tx_search.textChanged.connect(self._schedule_tx_filter)
        tl.addWidget(self.tx_search)
        copy_button = QPushButton('Gesamte Tabelle kopieren')
        from .table_copy import copy_table
        copy_button.clicked.connect(lambda: copy_table(self.tx))
        tb.addWidget(copy_button)
        self.tx=table(['Buchungstag','Konto / Depot','ID','Typ','Wertpapier','Betrag','Quelle','Verwendungszweck',
                       'Valuta','Vorgang','Referenz','Buchungstext','Auftraggeber/Empfänger','IBAN','BIC','Vollständiger Originaltext'])
        self.tx.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.tx.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        tl.addWidget(self.tx);self.tabs.addTab(tx,'Alle Buchungen')
        self.tx_details = QPlainTextEdit()
        self.tx_details.setReadOnly(True)
        self.tx_details.setPlaceholderText('Eine Buchung auswählen, um ihren vollständigen Text zu lesen.')
        self.tx_details.setMaximumHeight(230)
        tl.addWidget(self.tx_details)
        self.install_transaction_details()
        self.audit=table(['ID','Status','Zeit','Datei','Hinweise']);self.audit.cellDoubleClicked.connect(self.show_audit);audit_page=QWidget(); audit_layout=QVBoxLayout(audit_page); audit_bar=QHBoxLayout()
        self.audit.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.audit.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.audit.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        for label, callback in [('Konten zuordnen …', self.assign_selected_imports), ('Import korrigieren …', self.correct_selected_import), ('Import zurücknehmen', self.undo_selected_import), ('Ausgewählte Imports vollständig löschen …', self.delete_selected_imports)]:
            button=QPushButton(label); button.clicked.connect(callback); audit_bar.addWidget(button)
        audit_bar.addStretch(); audit_layout.addLayout(audit_bar); audit_layout.addWidget(self.audit)
        originals = QPushButton('Originaldateien speichern …')
        originals.clicked.connect(self.export_originals)
        audit_bar.addWidget(originals)
        reset = QPushButton('Alle Importe löschen …')
        reset.clicked.connect(self.delete_all_imports)
        audit_layout.addWidget(reset)
        self.tabs.addTab(audit_page,'Importprotokoll')
        from .bank_archive import BankArchiveWidget
        self.bank_archive = BankArchiveWidget(repository, account_getter, self)
        self.bank_archive.changed.connect(self.data_changed.emit)
        self.tabs.addTab(self.bank_archive, 'Bankarchiv')
        from .state_history_widget import StateHistoryWidget
        self.state_history = StateHistoryWidget(repository, account_getter, self)
        self.tabs.addTab(self.state_history, 'Bestandsverlauf')
        self.refresh()

    def assign_selected_imports(self):
        from .import_assignment import ImportAssignmentDialog
        ids = [int(self.audit.item(index.row(), 0).text()) for index in self.audit.selectionModel().selectedRows()]
        if not ids:
            QMessageBox.information(self, 'Imports auswählen', 'Bitte einen oder mehrere Imports auswählen (Strg/Shift für Mehrfachauswahl).')
            return
        try:
            dialog = ImportAssignmentDialog(self.repo, ids, self)
        except ValueError as error:
            QMessageBox.warning(self, 'Kontozuordnung', str(error))
            return
        if dialog.exec():
            self.refresh()
            self.data_changed.emit()

    def delete_all_imports(self):
        from .reset_data import confirm_reset
        if confirm_reset(self, self.repo):
            self.refresh()
            self.data_changed.emit()

    def delete_selected_imports(self):
        rows = sorted(index.row() for index in self.audit.selectionModel().selectedRows())
        if not rows:
            QMessageBox.information(self, 'Imports auswählen', 'Bitte einen oder mehrere Imports auswählen (Strg/Shift für Mehrfachauswahl).')
            return
        ids = [int(self.audit.item(row, 0).text()) for row in rows]
        entries = [f"{self.audit.item(row, 0).text()} · {self.audit.item(row, 3).text()}" for row in rows]
        box = QMessageBox(self)
        box.setWindowTitle('Imports vollständig löschen')
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText(f'{len(ids)} ausgewählte Imports endgültig löschen?')
        box.setInformativeText('Die zugehörigen Depotstände, Salden, Transaktionen, Importzuordnungen und Korrekturen werden aus der Datenbank entfernt. Dies kann nicht rückgängig gemacht werden. Frühere verbleibende Stände können wieder aktuell werden.\n\nKonten, gemerkte Importregeln und Quelldateien bleiben erhalten.')
        box.setDetailedText('\n'.join(entries))
        delete = box.addButton('Endgültig löschen', QMessageBox.ButtonRole.DestructiveRole)
        cancel = box.addButton('Abbrechen', QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel)
        box.setEscapeButton(cancel)
        box.exec()
        if box.clickedButton() != delete:
            return
        try:
            self.repo.delete_imports(ids)
        except Exception as error:
            QMessageBox.warning(self, 'Löschen fehlgeschlagen', str(error))
            return
        self.refresh()
        self.data_changed.emit()
    def refresh(self):
        if getattr(self.repo,'defer_initial_views',False): return
        self.refresh_wealth();self.refresh_compare();self.refresh_transactions();self.refresh_audit();self.bank_archive.refresh();self.state_history.refresh()
    def refresh_wealth(self):
        data=self.repo.wealth_series(self.ret.isChecked(),self.prop.isChecked(),self.debt.isChecked(),account=self.account_getter());cats=['Liquidität','Festgeld','Wertpapiere','Altersvorsorge','Immobilie (Schätzung)','Schulden'];fill(self.wealth_table,[(r['period'],euro(r['total']),*[euro(r['categories'].get(c,0)) for c in cats]) for r in data]);self.fig.clear();ax=self.fig.add_subplot(111)
        if data:
            dates=[date.fromisoformat(r['period']+'-01') for r in data];active=[]
            for cat in cats[:-1]:
                values=[float(r['categories'].get(cat,0)) for r in data]
                if any(values):active.append((cat,values))
            if active:
                ax.stackplot(dates,*[values for _,values in active],labels=[name.replace(' (Schätzung)','') for name,_ in active],colors=PALETTE[:len(active)],alpha=.70)
            totals=[float(r['total']) for r in data];ax.plot(dates,totals,color=COLORS['text'],linewidth=2,label='Nettovermögen');ax.annotate(compact_number(totals[-1]),(dates[-1],totals[-1]),xytext=(-5,8),textcoords='offset points',ha='right',fontsize=8,fontweight='bold',color=COLORS['text']);date_axis(ax);currency_axis(ax);style_axis(ax);ax.margins(x=.015);ax.legend(loc='upper left',ncol=min(4,len(active)+1),frameon=False,fontsize=8);ax.set_title('Vermögensentwicklung nach Anlageklasse',loc='left',fontsize=11,fontweight='bold',color=COLORS['text'])
        self.fig.subplots_adjust(left=.09,right=.98,top=.88,bottom=.14);self.canvas.draw_idle()
    def refresh_compare(self):
        rows=self.repo.compare(self.start.date().toString('yyyy-MM-dd'),self.end.date().toString('yyyy-MM-dd'),self.account_getter());fill(self.diff,[(r['account'],r['key'],r['name'],euro(r['before']),euro(r['after']),euro(r['change']),'' if r['quantity_change'] is None else float(r['quantity_change']),r['status']) for r in rows])
    def _schedule_tx_filter(self, *args):
        self._tx_filter_timer.start()
    def refresh_transactions(self):
        from portfolio_v5.booking_details import full_booking_text
        self._tx_rows = [((t['date'],t['account'],t['external_id'],t['kind'],t['security'],euro(t['amount']),
                 ', '.join(dict.fromkeys(Path(s['source']).name for s in t.get('booking_sources',[t]))),
                 *[t.get(k,'') for k in ('purpose','value_date','operation','bank_reference','booking_text','counterparty',
                                       'counterparty_iban','counterparty_bic')], full_booking_text(t)),
                          t.get('fees') not in (None, '')) for t in self.repo.transactions()]
        self.apply_transaction_filter()
    def apply_transaction_filter(self):
        if self._tx_rows is None:
            self.refresh_transactions(); return
        query = self.tx_search.text().strip().casefold()
        visible = [(row, has_fee) for row, has_fee in self._tx_rows
                   if not query or query in ' '.join(str(v) for v in row).casefold()]
        fill(self.tx, [row for row, _ in visible])
        fee_background, fee_foreground = QColor('#d9eeff'), QColor('#102a43')
        for row, (_, has_fee) in enumerate(visible):
            if has_fee:
                for column in range(self.tx.columnCount()):
                    item = self.tx.item(row, column)
                    if item:
                        item.setBackground(fee_background)
                        item.setForeground(fee_foreground)
        self.tx_details.clear()
        for column in (7, 11, 15): self.tx.setColumnWidth(column, 260)

    def install_transaction_details(self):
        def show(current, previous):
            row = current.row()
            self.tx_details.setPlainText('\n\n'.join(
                f'{self.tx.horizontalHeaderItem(c).text()}:\n{self.tx.item(row,c).text()}'
                for c in (7,15,9,10,11,12,13,14,0,8,1,5,4,3,6,2)
                if row >= 0 and self.tx.item(row,c) and self.tx.item(row,c).text()))
        self.tx.selectionModel().currentChanged.connect(show)

    def export_originals(self):
        folder = QFileDialog.getExistingDirectory(self, 'Originaldateien speichern')
        if not folder: return
        records = list(self.repo.store.db.execute('SELECT content_hash,path,content FROM original_files'))
        records += list(self.repo.store.db.execute('SELECT d.content_hash,i.path,d.content FROM bank_documents d JOIN imports i ON i.id=d.import_id'))
        seen = set()
        for record in records:
            key = (record['content_hash'], Path(record['path']).name)
            if key in seen: continue
            seen.add(key)
            target = Path(folder) / f'{record["content_hash"]}_{Path(record["path"]).name}'
            try:
                if target.exists():
                    if target.read_bytes() != record['content']:
                        raise ValueError(f'Datei mit anderem Inhalt vorhanden: {target.name}')
                else:
                    with target.open('xb') as output: output.write(record['content'])
            except (OSError, ValueError) as error:
                QMessageBox.warning(self, 'Originaldateien speichern', str(error))
                return
        QMessageBox.information(self, 'Originaldateien', f'{len(seen)} Originaldateien gespeichert.')
    def refresh_audit(self):
        fill(self.audit,[(r['id'],'aktiv' if r['active'] else 'zurückgenommen',r['imported_at'][:19],Path(r['path']).name,len(json.loads(r['report']).get('warnings',[]))) for r in self.repo.imports()])
    def confirm(self):
        account=self.account_getter()
        if not account:QMessageBox.warning(self,'Depot wählen','Bitte ein einzelnes Depot auswählen.');return
        self.repo.confirm_coverage(account,self.start.date().toString('yyyy-MM-dd'),self.end.date().toString('yyyy-MM-dd'));self.result.setText('Vollständigkeit bestätigt')
    def performance(self):
        r=security_performance(self.repo.store,self.account_getter(),self.start.date().toString('yyyy-MM-dd'),self.end.date().toString('yyyy-MM-dd'));self.result.setText(r.get('error') or f"XIRR {r['xirr']*100:.2f}% · Gewinn {euro(r['profit'])}")
    def show_audit(self,row,column):
        iid=int(self.audit.item(row,0).text());entry=next((x for x in self.repo.imports() if x['id']==iid),None)
        if entry:
            JsonReportDialog(iid, json.loads(entry['report']), self).exec()

    def correct_selected_import(self):
        from .import_correction import ImportCorrectionDialog
        row = self.audit.currentRow()
        if row < 0: return
        iid = int(self.audit.item(row,0).text())
        if not next(r for r in self.repo.imports() if r['id'] == iid)['active']:
            QMessageBox.information(self, 'Import wählen', 'Bitte einen aktiven Import auswählen.'); return
        if ImportCorrectionDialog(self.repo, iid, self).exec():
            self.refresh(); self.data_changed.emit()

    def undo_selected_import(self):
        row = self.audit.currentRow()
        if row < 0: return
        iid = int(self.audit.item(row,0).text())
        if QMessageBox.question(self, 'Import zurücknehmen', f'Import {iid} zurücknehmen? Die Daten bleiben im Protokoll erhalten.') == QMessageBox.StandardButton.Yes:
            self.repo.undo_import(iid); self.refresh(); self.data_changed.emit()
