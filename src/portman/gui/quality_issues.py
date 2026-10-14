"""Data-quality double-click repairs shared by the V07 and V09 windows."""
import json

from PySide6.QtWidgets import QInputDialog, QLabel, QMessageBox


def install_quality_links(window):
    window.quality_widget.table.cellDoubleClicked.connect(window.open_quality_issue)
    window.quality_widget.layout().insertWidget(
        0, QLabel('Doppelklick auf einen Hinweis öffnet die passende Korrektur oder Quelle.'))


def open_quality_issue(window, row, column):
    table = window.quality_widget.table
    kind, key = table.item(row, 1).text(), table.item(row, 2).text()
    if kind == 'Bewertung':
        account, day = window.dashboard_scope()
        candidates = [p for p in window.repository.holdings(day, account) if p['key'] == key]
        if not candidates: return
        labels = [f"{p['depot']} · {p['name']} · {p['as_of'] or p['period']}" for p in candidates]
        label, ok = QInputDialog.getItem(window, 'Einstand korrigieren', 'Datenstand:', labels, 0, False)
        if not ok: return
        selected = candidates[labels.index(label)]
        value, ok = QInputDialog.getText(window, 'Gesamteinstand', 'Gesamteinstand für diese Stückzahl in EUR (kein Stückpreis):')
        if not ok: return
        source, ok = QInputDialog.getText(window, 'Belegquelle', 'Belegname und Belegdatum:')
        if not ok: return
        try:
            from portfolio_v5.models import number
            window.repository.correct_cost(selected['snapshot_id'], key, number(value), source)
            window.reload_portfolio()
        except Exception as error: QMessageBox.warning(window, 'Einstand nicht gespeichert', str(error))
    elif kind == 'Stammdaten':
        message = table.item(row, 4).text()
        if 'Anzeigename' in message:
            name, ok = QInputDialog.getText(window, 'Anzeigename ergänzen', 'Kanonischer Anzeigename:')
            if ok and name.strip():
                with window.repository.db:
                    window.repository.db.execute('UPDATE security_master SET canonical_name=?,updated_at=CURRENT_TIMESTAMP WHERE security_key=?', (name.strip(), key))
                    window.repository.db.execute('UPDATE security_metadata SET display_name=?,updated_at=CURRENT_TIMESTAMP WHERE security_key=?', (name.strip(), key))
                window.reload_portfolio()
        else:
            window.repair_identity(key)
    elif kind == 'Klassifikation':
        from portman.classification_dialog import ClassificationDialog
        if ClassificationDialog(window.repository, key, window).exec(): window.reload_portfolio()
    elif kind == 'Import':
        window.show_workspace('history'); window.history_widget.tabs.setCurrentIndex(3)
        for i in range(window.history_widget.audit.rowCount()):
            if window.history_widget.audit.item(i, 0).text() == key: window.history_widget.audit.selectRow(i); break
    else: window.open_evidence()


def repair_identity(window, key):
    from portfolio_v5.models import valid_isin
    account, day = window.dashboard_scope()
    candidates = [p for p in window.repository.holdings(day, account) if p['key'] == key]
    if not candidates: return
    labels = [f"{p['depot']} · {p['name']} · {p['as_of'] or p['period']}" for p in candidates]
    label, ok = QInputDialog.getItem(window, 'Bestandsbeleg wählen', 'Welche Position korrigieren?', labels, 0, False)
    if not ok: return
    selected = candidates[labels.index(label)]
    isin, ok = QInputDialog.getText(window, 'ISIN anhand des Belegs korrigieren',
        'Gültige ISIN aus dem Originalbeleg. Die Korrektur erstellt eine neue Importrevision.\nAndere Datenstände und Buchungskennungen bleiben unverändert; anschließend Abstimmung prüfen.')
    if not ok: return
    isin = isin.strip().upper()
    if not valid_isin(isin):
        QMessageBox.warning(window, 'ISIN prüfen', 'Die ISIN oder ihre Prüfziffer ist ungültig.'); return
    try:
        row = window.repository.db.execute('SELECT import_id,payload FROM snapshots WHERE id=?', (selected['snapshot_id'],)).fetchone()
        payload = json.loads(row['payload'])
        if any(p['key'] == isin and p['key'] != key for p in payload['positions']):
            raise ValueError('Diese ISIN existiert bereits im Datenstand. Bitte den Quellbestand prüfen.')
        for position in payload['positions']:
            if position['key'] == key: position.update(key=isin, isin=isin)
        window.repository.correct_import(row['import_id'], {'snapshots': {selected['snapshot_id']: {'positions': payload['positions']}}})
        window.repository.sync_security_master(); window.reload_portfolio()
    except Exception as error: QMessageBox.warning(window, 'Korrektur fehlgeschlagen', str(error))
